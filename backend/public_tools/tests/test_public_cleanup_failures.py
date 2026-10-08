"""Failed PDF deletion keeps the public comparison available for TTL recovery."""

import logging
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from freezegun import freeze_time

from documents.services import storage_service
from public_tools.models import PublicComparison
from public_tools.services.public_comparison_service import storage_key_for
from public_tools.tasks import purge_expired_public_comparisons, run_public_comparison

pytestmark = pytest.mark.django_db
TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


def _keys(comparison):
    return {
        slot: storage_key_for(comparison.public_id, slot)
        for slot in ('a', 'b')
    }


def _store_files(comparison):
    keys = _keys(comparison)
    storage_service.put_bytes(
        keys['a'], (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf'
    )
    storage_service.put_bytes(
        keys['b'], (TESTDATA / 'contrato_v2.pdf').read_bytes(), 'application/pdf'
    )
    return keys


def _expire(comparison):
    comparison.expires_at = timezone.now() - timedelta(seconds=1)
    comparison.save(update_fields=['expires_at'])


def _refuse_delete(monkeypatch, refused_key, error):
    delete = storage_service.delete
    attempts = []

    def guarded_delete(key):
        attempts.append(key)
        if key == refused_key:
            raise error
        delete(key)

    monkeypatch.setattr(storage_service, 'delete', guarded_delete)
    return attempts


@pytest.fixture
def stored_comparison():
    comparison = PublicComparison.objects.create(
        file_a_name='private-a.pdf',
        file_b_name='private-b.pdf',
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return comparison, _store_files(comparison)


@pytest.fixture
def expired_comparison(stored_comparison):
    comparison, keys = stored_comparison
    _expire(comparison)
    return comparison, keys


@pytest.mark.parametrize('slot', ['a', 'b'])
@pytest.mark.parametrize('error_type', [PermissionError, OSError])
def test_failed_purge_remains_retryable(expired_comparison, monkeypatch, slot, error_type):
    comparison, keys = expired_comparison
    retained_bytes = storage_service.get_bytes(keys[slot])
    sibling = {'a': 'b', 'b': 'a'}[slot]

    with monkeypatch.context() as failure:
        _refuse_delete(failure, keys[slot], error_type('storage unavailable'))
        purged = purge_expired_public_comparisons()

    assert purged == 0
    assert PublicComparison.objects.filter(
        pk=comparison.pk, public_id=comparison.public_id, expires_at=comparison.expires_at
    ).exists()
    assert storage_service.get_bytes(keys[slot]) == retained_bytes
    assert storage_service.head(keys[sibling]) is None

    recovered = purge_expired_public_comparisons()

    assert recovered == 1
    assert not PublicComparison.objects.filter(pk=comparison.pk).exists()
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None


@pytest.mark.parametrize('failed_index', [0, 99])
@freeze_time('2026-10-08 12:00:00')
def test_purge_progresses_past_retained_comparison(monkeypatch, failed_index):
    PublicComparison.objects.bulk_create([
        PublicComparison(
            result={'private_result': 'x' * 4096},
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        for _ in range(101)
    ])
    expired = list(PublicComparison.objects.only('pk', 'public_id').order_by('pk'))
    failed = expired[failed_index]
    failed_keys = _store_files(failed)
    following_keys = _store_files(expired[-1])
    attempts = _refuse_delete(
        monkeypatch, failed_keys['a'], PermissionError('storage unavailable')
    )

    with CaptureQueriesContext(connection) as queries:
        purged = purge_expired_public_comparisons()

    assert purged == 100
    assert list(PublicComparison.objects.values_list('pk', flat=True)) == [failed.pk]
    assert storage_service.head(failed_keys['a']) is not None
    assert storage_service.head(failed_keys['b']) is None
    assert storage_service.head(following_keys['a']) is None
    assert storage_service.head(following_keys['b']) is None
    assert attempts.count(failed_keys['a']) == 1
    fetches = [
        entry['sql'] for entry in queries.captured_queries
        if entry['sql'].lstrip().upper().startswith('SELECT')
        and 'public_tools_publiccomparison' in entry['sql']
    ]
    assert len(fetches) == 3
    assert all('LIMIT 100' in query for query in fetches)
    assert all('result' not in query.lower() for query in fetches)


def test_purge_waits_for_both_deletions(expired_comparison, monkeypatch):
    comparison, keys = expired_comparison

    def unavailable_delete(key):
        raise OSError('storage unavailable')

    with monkeypatch.context() as failure:
        failure.setattr(storage_service, 'delete', unavailable_delete)
        first_purge = purge_expired_public_comparisons()

    assert first_purge == 0
    assert PublicComparison.objects.filter(pk=comparison.pk).exists()
    assert storage_service.head(keys['a']) is not None
    assert storage_service.head(keys['b']) is not None

    with monkeypatch.context() as failure:
        _refuse_delete(failure, keys['b'], PermissionError('storage unavailable'))
        partial_purge = purge_expired_public_comparisons()

    assert partial_purge == 0
    assert PublicComparison.objects.filter(pk=comparison.pk).exists()
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is not None

    recovered = purge_expired_public_comparisons()

    assert recovered == 1
    assert not PublicComparison.objects.filter(pk=comparison.pk).exists()
    assert storage_service.head(keys['b']) is None


@pytest.mark.parametrize('slot', ['a', 'b'])
def test_processing_cleanup_failure_remains_recoverable(stored_comparison, monkeypatch, slot):
    comparison, keys = stored_comparison
    expires_at = comparison.expires_at
    sibling = {'a': 'b', 'b': 'a'}[slot]

    with monkeypatch.context() as failure:
        _refuse_delete(failure, keys[slot], PermissionError('storage unavailable'))
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.DONE
    assert comparison.result['counts']['modified'] == 2
    assert comparison.error_code == ''
    assert comparison.expires_at == expires_at
    assert storage_service.head(keys[slot]) is not None
    assert storage_service.head(keys[sibling]) is None

    _expire(comparison)
    recovered = purge_expired_public_comparisons()

    assert recovered == 1
    assert not PublicComparison.objects.filter(pk=comparison.pk).exists()
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None


def test_failed_processing_retains_original_error_code(stored_comparison, monkeypatch):
    comparison, keys = stored_comparison
    expires_at = comparison.expires_at

    def unavailable_read(key):
        raise storage_service.StorageUnavailable('private processing failure')

    monkeypatch.setattr(storage_service, 'get_bytes', unavailable_read)
    _refuse_delete(monkeypatch, keys['a'], PermissionError('cleanup failure'))

    run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.FAILED
    assert comparison.error_code == 'processing_failed'
    assert comparison.result is None
    assert comparison.expires_at == expires_at
    assert storage_service.head(keys['a']) is not None
    assert storage_service.head(keys['b']) is None


def test_ocr_rejection_survives_cleanup_failure(stored_comparison, monkeypatch):
    comparison, keys = stored_comparison
    expires_at = comparison.expires_at
    storage_service.put_bytes(
        keys['a'], (TESTDATA / 'escaneado_v1.pdf').read_bytes(), 'application/pdf'
    )
    _refuse_delete(monkeypatch, keys['a'], PermissionError('cleanup failure'))

    run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.FAILED
    assert comparison.error_code == 'ocr_required'
    assert comparison.result is None
    assert comparison.expires_at == expires_at
    assert storage_service.head(keys['a']) is not None
    assert storage_service.head(keys['b']) is None


def test_interrupted_processing_preserves_original_exception(stored_comparison, monkeypatch):
    comparison, keys = stored_comparison
    interrupted = KeyboardInterrupt('processing interrupted')

    def interrupted_read(key):
        raise interrupted

    monkeypatch.setattr(storage_service, 'get_bytes', interrupted_read)
    _refuse_delete(monkeypatch, keys['a'], PermissionError('cleanup failure'))

    with pytest.raises(KeyboardInterrupt) as raised:
        run_public_comparison.run(comparison.pk)

    assert raised.value is interrupted
    assert PublicComparison.objects.filter(
        pk=comparison.pk, status=PublicComparison.Status.PROCESSING
    ).exists()
    assert storage_service.head(keys['a']) is not None
    assert storage_service.head(keys['b']) is None


def test_cleanup_warning_contains_safe_diagnostics(expired_comparison, monkeypatch, caplog):
    comparison, keys = expired_comparison
    private_detail = '/private/objects/private-a.pdf %PDF-sensitive-content'
    _refuse_delete(monkeypatch, keys['a'], PermissionError(private_detail))

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        purged = purge_expired_public_comparisons()

    assert purged == 0
    assert PublicComparison.objects.filter(pk=comparison.pk).exists()
    records = [record for record in caplog.records if record.name == 'public_tools.tasks']
    assert len(records) == 1
    assert records[0].getMessage() == (
        'Public comparison cleanup deferred: phase=expired_purge error_class=PermissionError'
    )
    assert records[0].phase == 'expired_purge'
    assert records[0].error_class == 'PermissionError'
    assert records[0].exc_info is None
    assert records[0].args == ('PermissionError',)
    assert private_detail not in caplog.text
    assert keys['a'] not in caplog.text
    assert comparison.file_a_name not in caplog.text
