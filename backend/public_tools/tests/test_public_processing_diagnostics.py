"""Public processing failures retain useful diagnostics without private PDF data."""

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.db import OperationalError, connection
from documents.services import storage_service

from public_tools.models import PublicComparison
from public_tools.services.public_comparison_service import storage_key_for
from public_tools.tasks import run_public_comparison

pytestmark = pytest.mark.django_db
TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'
PRIVATE_DETAIL = '/private/objects/private-a.pdf %PDF-sensitive-content token=private-token'
LOG_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {'message', 'asctime'}


@pytest.fixture
def stored_comparison():
    """Store real deterministic PDFs for a pending comparison."""
    comparison = PublicComparison.objects.create(
        file_a_name='private-a.pdf',
        file_b_name='private-b.pdf',
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    keys = {
        slot: storage_key_for(comparison.public_id, slot)
        for slot in ('a', 'b')
    }
    storage_service.put_bytes(
        keys['a'], (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf'
    )
    storage_service.put_bytes(
        keys['b'], (TESTDATA / 'contrato_v2.pdf').read_bytes(), 'application/pdf'
    )
    return comparison, keys


def _refuse_read(monkeypatch, refused_key, error):
    """Inject a failure at the object-storage boundary for one object only."""
    read = storage_service.get_bytes

    def guarded_read(key):
        if key == refused_key:
            raise error
        return read(key)

    monkeypatch.setattr(storage_service, 'get_bytes', guarded_read)


def _records(caplog):
    """Project emitted records, including every custom field and traceback slot."""
    return [
        (
            record.levelno, record.getMessage(),
            getattr(record, 'phase', None), getattr(record, 'error_class', None),
            record.args, record.exc_info, record.exc_text,
            set(record.__dict__) - LOG_FIELDS,
        )
        for record in caplog.records
        if record.name == 'public_tools.tasks'
    ]


def _processing_record(phase, error_class):
    """Return the expected bounded diagnostic without an exception payload."""
    return (
        logging.ERROR,
        f'Public comparison processing failed: phase={phase} error_class={error_class}',
        phase, error_class, (phase, error_class), None, None, {'phase', 'error_class'},
    )


def _private_values(comparison, keys):
    """Private details that must not enter a diagnostic through arguments or extras."""
    return (
        PRIVATE_DETAIL, keys['a'], keys['b'], comparison.file_a_name,
        comparison.file_b_name, str(comparison.public_id),
    )


@pytest.mark.parametrize('slot', ['a', 'b'])
def test_read_failure_identifies_storage_phase(stored_comparison, monkeypatch, caplog, slot):
    """Identify either failed storage read while keeping the public failure contract."""
    comparison, keys = stored_comparison
    _refuse_read(monkeypatch, keys[slot], storage_service.StorageUnavailable(PRIVATE_DETAIL))

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.FAILED
    assert comparison.error_code == 'processing_failed'
    assert comparison.result is None
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == [_processing_record(f'read_{slot}', 'StorageUnavailable')]
    assert not any(value in caplog.text for value in _private_values(comparison, keys))


def test_corrupt_pdf_identifies_build_phase(stored_comparison, caplog):
    """The real PDF parser produces a sanitized build-result diagnostic."""
    comparison, keys = stored_comparison
    storage_service.put_bytes(
        keys['a'], (TESTDATA / 'corrupto.pdf').read_bytes(), 'application/pdf'
    )

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.FAILED
    assert comparison.error_code == 'processing_failed'
    assert comparison.result is None
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == [_processing_record('build_result', 'InvalidPdfError')]
    assert not any(value in caplog.text for value in _private_values(comparison, keys))


@pytest.fixture
def rejected_result_updates():
    """Reject one result UPDATE at the SQL boundary; subsequent state writes work."""
    rejected = []
    update_prefix = f'UPDATE {connection.ops.quote_name(PublicComparison._meta.db_table)} SET '
    result_assignment = f'{connection.ops.quote_name("result")} = '

    def reject_once(execute, sql, params, many, context):
        if not rejected and sql.startswith(update_prefix) and result_assignment in sql:
            rejected.append(True)
            raise OperationalError(PRIVATE_DETAIL)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(reject_once):
        yield rejected


@pytest.mark.django_db(transaction=True)
def test_result_write_failure_identifies_persist_phase(
    stored_comparison, rejected_result_updates, caplog,
):
    """A rejected SQL write in worker-style autocommit still permits FAILED persistence."""
    comparison, keys = stored_comparison

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert rejected_result_updates == [True]
    assert (comparison.status, comparison.error_code, comparison.result) == (
        PublicComparison.Status.FAILED, 'processing_failed', None,
    )
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == [_processing_record('persist_result', 'OperationalError')]
    assert not any(value in caplog.text for value in _private_values(comparison, keys))


def test_soft_timeout_identifies_interrupted_phase(stored_comparison, monkeypatch, caplog):
    """A simulated Celery interruption retains the interrupted storage phase."""
    comparison, keys = stored_comparison
    _refuse_read(monkeypatch, keys['a'], SoftTimeLimitExceeded(PRIVATE_DETAIL))

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.FAILED
    assert comparison.error_code == 'processing_failed'
    assert comparison.result is None
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == [_processing_record('read_a', 'SoftTimeLimitExceeded')]
    assert not any(value in caplog.text for value in _private_values(comparison, keys))


@pytest.fixture
def rejected_cleanup(stored_comparison, monkeypatch):
    """Refuse deletion of A while allowing real deletion of the sibling PDF."""
    _, keys = stored_comparison
    delete = storage_service.delete

    def guarded_delete(key):
        if key == keys['a']:
            raise PermissionError(PRIVATE_DETAIL)
        return delete(key)

    monkeypatch.setattr(storage_service, 'delete', guarded_delete)


def test_cleanup_failure_preserves_processing_diagnostic(
    stored_comparison, rejected_cleanup, monkeypatch, caplog,
):
    """A later cleanup warning must not replace the original processing ERROR."""
    comparison, keys = stored_comparison
    retained_bytes = storage_service.get_bytes(keys['a'])
    _refuse_read(monkeypatch, keys['a'], storage_service.StorageUnavailable(PRIVATE_DETAIL))

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert (comparison.status, comparison.error_code, comparison.result) == (
        PublicComparison.Status.FAILED, 'processing_failed', None,
    )
    assert storage_service.head(keys['a'])['ContentLength'] == len(retained_bytes)
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == [
        _processing_record('read_a', 'StorageUnavailable'),
        (
            logging.WARNING,
            'Public comparison cleanup deferred: phase=processing_cleanup '
            'error_class=PermissionError',
            'processing_cleanup', 'PermissionError', ('PermissionError',),
            None, None, {'phase', 'error_class'},
        ),
    ]
    assert not any(value in caplog.text for value in _private_values(comparison, keys))


def test_successful_comparison_emits_no_processing_error(stored_comparison, caplog):
    """Real fixture comparison remains successful without spurious failure signals."""
    comparison, keys = stored_comparison

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.DONE
    assert comparison.error_code == ''
    assert {
        change: comparison.result['counts'][change]
        for change in ('modified', 'removed', 'added')
    } == {'modified': 2, 'removed': 1, 'added': 1}
    assert comparison.result['summary_text'] == '2 modificadas, 1 eliminada, 1 agregada'
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == []


def test_ocr_rejection_emits_no_processing_error(stored_comparison, caplog):
    """The real scanned fixture retains its expected public OCR rejection."""
    comparison, keys = stored_comparison
    storage_service.put_bytes(
        keys['a'], (TESTDATA / 'escaneado_v1.pdf').read_bytes(), 'application/pdf'
    )

    with caplog.at_level(logging.WARNING, logger='public_tools.tasks'):
        run_public_comparison.run(comparison.pk)

    comparison.refresh_from_db()
    assert comparison.status == PublicComparison.Status.FAILED
    assert comparison.error_code == 'ocr_required'
    assert comparison.result is None
    assert storage_service.head(keys['a']) is None
    assert storage_service.head(keys['b']) is None
    assert _records(caplog) == []
