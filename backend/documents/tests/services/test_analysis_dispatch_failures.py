"""A persisted upload remains recoverable when broker publication fails."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from django.db import transaction
from django.utils import timezone
from kombu.exceptions import OperationalError

from documents.models import DocumentVersion
from documents.services import storage_service, version_service
from engine import tasks
from engine.models import EngineJob

TESTDATA = Path(__file__).resolve().parents[4] / 'testdata' / 'pdfs'


@pytest.fixture
def staged_upload(versiona_context, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    editor = versiona_context.users['editor']
    document = version_service.create_document(versiona_context.project, 'Contrato', editor)
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(intent.key, (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf')
    return document, intent, editor


@pytest.fixture
def broker(monkeypatch):
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
def test_dispatch_recovery_finishes_the_original_upload(
    staged_upload, broker, django_capture_on_commit_callbacks,
):
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
    assert version.section_versions.count() == 8
    assert DocumentVersion.objects.filter(document=document).count() == 1


@pytest.mark.django_db
def test_outer_upload_transaction_defers_publication(
    staged_upload, broker, django_capture_on_commit_callbacks,
):
    document, intent, editor = staged_upload
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            version, job = version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
            broker.assert_not_called()

    assert broker.call_count == 1
    assert EngineJob.objects.get(pk=job.pk).document_version_id == version.pk


@pytest.mark.django_db
def test_outer_upload_rollback_discards_publication(staged_upload, broker):
    document, intent, editor = staged_upload

    with pytest.raises(ValueError, match='cancelled'):
        with transaction.atomic():
            version_service.complete_upload(document, intent.upload_id, 'Entrega', editor)
            raise ValueError('cancelled')

    broker.assert_not_called()
    assert not EngineJob.objects.exists()
    assert not DocumentVersion.objects.filter(document=document).exists()
