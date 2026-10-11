"""A persisted upload remains recoverable when broker publication fails."""

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.db import OperationalError as DatabaseOperationalError
from django.db import connection, transaction
from django.utils import timezone
from engine import tasks
from engine.models import EngineJob
from freezegun import freeze_time
from kombu.exceptions import OperationalError

from documents.models import DocumentVersion
from documents.services import storage_service, version_service

TESTDATA = Path(__file__).resolve().parents[4] / 'testdata' / 'pdfs'


@pytest.fixture
def staged_upload(versiona_context, settings):
    """Store a deterministic PDF for an asynchronous upload."""
    settings.CELERY_TASK_ALWAYS_EAGER = False
    editor = versiona_context.users['editor']
    document = version_service.create_document(versiona_context.project, 'Contrato', editor)
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(intent.key, (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf')
    return document, intent, editor


@pytest.fixture
def broker(monkeypatch):
    """Simulate the broker publication boundary without network access."""
    connection = MagicMock()
    connection.__enter__.return_value = connection
    producer = connection.Producer.return_value
    producer.__enter__.return_value = producer
    monkeypatch.setattr(tasks.run_analysis.app, 'connection_for_write', MagicMock(return_value=connection))
    publish = MagicMock(side_effect=OperationalError('private broker address'))
    monkeypatch.setattr(tasks.run_analysis, 'apply_async', publish)
    return publish


@pytest.mark.django_db
def test_upload_returns_202_when_publication_fails(
    staged_upload, broker, client_as, django_capture_on_commit_callbacks,
):
    """Upload returns 202 when publication fails."""
    document, intent, _editor = staged_upload

    with django_capture_on_commit_callbacks(execute=True):
        response = client_as('editor').post(
            f'/api/documents/{document.public_id}/versions/complete/',
            {'upload_id': intent.upload_id, 'message': 'Primera entrega'}, format='json',
        )

    assert response.status_code == 202
    job = EngineJob.objects.get(public_id=response.data['job_id'])
    assert job.status == EngineJob.Status.PENDING
    assert job.celery_task_id == ''
    assert str(job.document_version.public_id) == response.data['version']['public_id']
    assert DocumentVersion.objects.filter(document=document).count() == 1


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_dispatch_recovery_finishes_the_original_upload(
    staged_upload, broker, django_capture_on_commit_callbacks,
):
    """Dispatch recovery finishes the original upload."""
    document, intent, editor = staged_upload
    with django_capture_on_commit_callbacks(execute=True):
        version, job = version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
    EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=61))
    broker.side_effect = None

    assert tasks.recover_pending_analysis() == 1
    tasks.run_analysis(job.pk)

    job.refresh_from_db()
    version.refresh_from_db()
    assert job.status == EngineJob.Status.DONE
    assert version.analysis_status == DocumentVersion.AnalysisStatus.READY
    # Eight numbered sections plus the detected preamble.
    assert version.section_versions.count() == 9
    assert DocumentVersion.objects.filter(document=document).count() == 1


@pytest.mark.django_db
def test_outer_upload_transaction_defers_publication(
    staged_upload, broker, django_capture_on_commit_callbacks,
):
    """Outer upload transaction defers publication."""
    document, intent, editor = staged_upload
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            version, job = version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
            broker.assert_not_called()

    assert broker.call_count == 1
    assert EngineJob.objects.get(pk=job.pk).document_version_id == version.pk


@pytest.mark.django_db
def test_outer_upload_rollback_discards_publication(staged_upload, broker):
    """Outer upload rollback discards publication."""
    document, intent, editor = staged_upload

    with pytest.raises(ValueError, match='cancelled'):
        _complete_then_rollback(document, intent, editor)

    broker.assert_not_called()
    assert not EngineJob.objects.exists()
    assert not DocumentVersion.objects.filter(document=document).exists()


def _complete_then_rollback(document, intent, editor):
    with transaction.atomic():
        version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
        raise ValueError('cancelled')


@contextmanager
def _analysis_intent_disconnect():
    """Interrupt the SQL transport on the real ORM's analysis-job INSERT."""
    failures = []
    insert_prefix = f'INSERT INTO {connection.ops.quote_name(EngineJob._meta.db_table)} '

    def unavailable_insert(execute, sql, params, many, context):
        if sql.startswith(insert_prefix):
            failures.append(sql)
            raise DatabaseOperationalError(2006, 'simulated database disconnect')
        return execute(sql, params, many, context)

    with connection.execute_wrapper(unavailable_insert):
        yield failures


@pytest.fixture
def unavailable_analysis_intent():
    """Fail SQL insertion while preserving real ORM and transaction behavior."""
    with _analysis_intent_disconnect() as failures:
        yield failures


@pytest.mark.django_db(transaction=True)
def test_analysis_intent_failure_rolls_back_version_allocation(staged_upload, unavailable_analysis_intent):
    """Catches: committing an upload whose analysis cannot be recovered."""
    document, intent, editor = staged_upload

    with pytest.raises(DatabaseOperationalError, match='simulated database disconnect'):
        version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)

    document.refresh_from_db()
    assert (
        DocumentVersion.objects.filter(document=document).count(),
        EngineJob.objects.count(),
        document.latest_number,
    ) == (0, 0, 0)


@pytest.mark.django_db(transaction=True)
def test_analysis_intent_failure_preserves_staging(staged_upload, unavailable_analysis_intent):
    """Catches: consuming the only retryable upload before its job exists."""
    document, intent, editor = staged_upload
    payload = storage_service.get_bytes(intent.key)

    with pytest.raises(DatabaseOperationalError, match='simulated database disconnect'):
        version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)

    assert storage_service.get_bytes(intent.key) == payload


@pytest.mark.django_db(transaction=True)
def test_analysis_intent_failure_does_not_promote_pdf(staged_upload, unavailable_analysis_intent):
    """Catches: creating a final object without a durable analysis intent."""
    document, intent, editor = staged_upload

    with pytest.raises(DatabaseOperationalError, match='simulated database disconnect'):
        version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)

    assert storage_service.head(storage_service.version_key(document, 1)) is None


@pytest.mark.django_db(transaction=True)
def test_analysis_intent_failure_preserves_existing_final_pdf(staged_upload, unavailable_analysis_intent):
    """Catches: overwriting or deleting an object before intent creation succeeds."""
    document, intent, editor = staged_upload
    final_key = storage_service.version_key(document, 1)
    previous = b'previous uncommitted promotion'
    storage_service.put_bytes(final_key, previous, 'application/pdf')

    with pytest.raises(DatabaseOperationalError, match='simulated database disconnect'):
        version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)

    assert storage_service.get_bytes(final_key) == previous


@pytest.mark.django_db(transaction=True)
@freeze_time('2026-10-11T12:00:00Z')
def test_original_upload_retries_after_analysis_intent_failure(staged_upload, broker):
    """Catches: an insertion failure permanently stranding the original upload."""
    document, intent, editor = staged_upload
    with _analysis_intent_disconnect() as failures:
        with pytest.raises(DatabaseOperationalError, match='simulated database disconnect'):
            version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
    assert len(failures) == 1

    version, job = version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
    EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=61))
    broker.side_effect = None

    assert tasks.recover_pending_analysis() == 1
    tasks.run_analysis(job.pk)

    version.refresh_from_db()
    job.refresh_from_db()
    assert version.analysis_status == DocumentVersion.AnalysisStatus.READY
    assert job.status == EngineJob.Status.DONE
    assert DocumentVersion.objects.filter(document=document).count() == 1
    assert EngineJob.objects.filter(document_version=version).count() == 1


@pytest.mark.django_db(transaction=True)
@freeze_time('2026-10-11T12:00:00Z')
def test_dispatch_callback_failure_keeps_a_recoverable_upload(staged_upload, broker):
    """Catches: discarding the committed upload after publication setup fails."""
    document, intent, editor = staged_upload
    payload = storage_service.get_bytes(intent.key)
    failures = []
    job_table = f'FROM {connection.ops.quote_name(EngineJob._meta.db_table)} '

    def unavailable_dispatch(execute, sql, params, many, context):
        if sql.startswith('SELECT ') and job_table in sql and sql.endswith('FOR UPDATE'):
            failures.append(sql)
            raise DatabaseOperationalError(2006, 'simulated dispatch disconnect')
        return execute(sql, params, many, context)

    with connection.execute_wrapper(unavailable_dispatch):
        with pytest.raises(DatabaseOperationalError, match='simulated dispatch disconnect'):
            version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
    assert len(failures) == 1
    version = DocumentVersion.objects.get(document=document)
    job = EngineJob.objects.get(document_version=version)
    assert storage_service.get_bytes(version.file_key) == payload
    EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=61))
    broker.side_effect = None

    assert tasks.recover_pending_analysis() == 1
    tasks.run_analysis(job.pk)

    job.refresh_from_db()
    assert job.status == EngineJob.Status.DONE
