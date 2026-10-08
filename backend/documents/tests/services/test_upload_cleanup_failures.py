"""Post-promotion cleanup cannot strand an otherwise completed upload."""

import logging
from pathlib import Path

import pytest

from documents.models import DocumentVersion
from documents.services import storage_service, version_service

TESTDATA = Path(__file__).resolve().parents[4] / 'testdata' / 'pdfs'


@pytest.mark.django_db
@pytest.mark.parametrize('error_type', [PermissionError, OSError])
def test_staging_cleanup_failure_preserves_completed_upload(
    versiona_context, monkeypatch, caplog, error_type
):
    """Preserve the completed upload when temporary cleanup fails."""
    editor = versiona_context.users['editor']
    document = version_service.create_document(
        versiona_context.project, 'Contrato privado', editor
    )
    intent = version_service.create_upload_intent(document, editor)
    payload = (TESTDATA / 'contrato_v1.pdf').read_bytes()
    storage_service.put_bytes(intent.key, payload, 'application/pdf')
    private_detail = '/private/uploads/contract.pdf %PDF-sensitive-content'

    def unavailable_delete(key):
        raise error_type(private_detail)

    monkeypatch.setattr(storage_service, 'delete', unavailable_delete)

    with caplog.at_level(logging.WARNING, logger='documents.services.version_service'):
        version, job = version_service.complete_upload(
            document, intent.upload_id, 'Primera entrega', editor
        )

    assert DocumentVersion.objects.filter(pk=version.pk, document=document, number=1).exists()
    assert version.analysis_status == DocumentVersion.AnalysisStatus.READY
    assert version.section_versions.exists()
    assert job.status == 'done'
    assert storage_service.get_bytes(version.file_key) == payload
    assert storage_service.get_bytes(intent.key) == payload
    records = [
        record for record in caplog.records
        if record.name == 'documents.services.version_service'
    ]
    assert len(records) == 1
    assert records[0].phase == 'upload_cleanup'
    assert records[0].error_class == error_type.__name__
    assert f'phase=upload_cleanup error_class={error_type.__name__}' in records[0].getMessage()
    assert records[0].exc_info is None
    assert private_detail not in caplog.text
    assert intent.key not in caplog.text
