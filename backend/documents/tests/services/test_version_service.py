"""End-to-end backend slice of C1/C2 (real MinIO + eager Celery) and the
draft-message rule I2b. Scenario ids per docs/audit/03."""

from pathlib import Path

import pytest

from audit.models import AuditEvent
from documents.models import DocumentVersion, SectionVersion
from documents.services import storage_service, version_service
from documents.services.storage import filesystem

TESTDATA = Path(__file__).resolve().parents[4] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_storage_prefix(settings):
    settings.DJANGO_ENV = 'test'


@pytest.fixture
def document(versiona_context):
    return version_service.create_document(
        versiona_context.project, 'Contrato de obra', versiona_context.users['editor']
    )


def upload(document, user, fixture='contrato_v1.pdf', message='primera entrega'):
    intent = version_service.create_upload_intent(document, user)
    storage_service.put_bytes(intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf')
    return version_service.complete_upload(document, intent.upload_id, message, user)


def _replace_staging_after_read(operation, staging_key, replacement):
    """Interleave a real staging write after an existing storage read."""
    def replacing_read(key):
        result = operation(key)
        if key == staging_key:
            storage_service.put_bytes(key, replacement, 'application/pdf')
        return result

    return replacing_read


@pytest.mark.django_db
@pytest.mark.escenario('C1-F01')
def test_complete_upload_analyzes_and_indexes_sections(document, versiona_context):
    version, job = upload(document, versiona_context.users['editor'])

    version.refresh_from_db()
    assert version.number == 1
    assert version.analysis_status == DocumentVersion.AnalysisStatus.READY
    assert version.page_count > 0
    assert version.thumb_status == DocumentVersion.ThumbStatus.READY
    keys = set(
        SectionVersion.objects.filter(document_version=version)
        .values_list('section__stable_key', flat=True)
    )
    assert 'objeto-del-contrato' in keys
    assert 'plazo-de-ejecucion' in keys
    assert job.status == 'done'


@pytest.mark.django_db
@pytest.mark.escenario('C2-F01')
def test_second_version_matches_identity_and_retires_removed(document, versiona_context):
    editor = versiona_context.users['editor']
    upload(document, editor)

    v2, job = upload(document, editor, 'contrato_v2.pdf', 'atiende observaciones')

    v2.refresh_from_db()
    assert v2.number == 2
    assert job.result['sections']['removed'] == 1  # plazo-de-ejecucion
    retired = document.sections.filter(retired_in_version=v2).values_list('stable_key', flat=True)
    assert list(retired) == ['plazo-de-ejecucion']
    added = document.sections.filter(created_in_version=v2).values_list('stable_key', flat=True)
    assert 'proteccion-de-datos-personales' in added


@pytest.mark.django_db
@pytest.mark.escenario('C2-E01')
def test_identical_binary_is_rejected(document, versiona_context):
    editor = versiona_context.users['editor']
    upload(document, editor)

    with pytest.raises(version_service.DomainError) as excinfo:
        upload(document, editor, 'contrato_v1.pdf', 'reintento')

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('C1-E01')
def test_protected_pdf_is_rejected_with_actionable_message(document, versiona_context):
    with pytest.raises(version_service.DomainError, match='contraseña'):
        upload(document, versiona_context.users['editor'], 'protegido.pdf')


@pytest.mark.django_db
@pytest.mark.escenario('C1-E02')
def test_corrupt_file_is_rejected(document, versiona_context):
    with pytest.raises(version_service.DomainError, match='PDF'):
        upload(document, versiona_context.users['editor'], 'corrupto.pdf')


@pytest.mark.django_db
@pytest.mark.escenario('C1-E03')
@pytest.mark.escenario('C2-E03')
def test_oversized_upload_is_rejected(document, versiona_context, settings):
    settings.MAX_PDF_SIZE_MB = 0

    with pytest.raises(version_service.DomainError) as excinfo:
        upload(document, versiona_context.users['editor'])

    assert excinfo.value.status_code == 413


@pytest.mark.django_db
@pytest.mark.escenario('C2-A01')
def test_message_editable_while_draft_with_audit_trail(document, versiona_context):
    editor = versiona_context.users['editor']
    version, _ = upload(document, editor)

    version_service.edit_message(version, 'mensaje corregido', editor)

    version.refresh_from_db()
    assert version.message == 'mensaje corregido'
    event = AuditEvent.objects.filter(event_type='version.message_edited').latest('created_at')
    assert event.payload == {'before': 'primera entrega', 'after': 'mensaje corregido'}


@pytest.mark.django_db
@pytest.mark.escenario('C2-E02')
def test_message_frozen_once_approved(document, versiona_context):
    editor = versiona_context.users['editor']
    version, _ = upload(document, editor)
    DocumentVersion.all_objects.filter(pk=version.pk).update(is_approved=True)
    version.refresh_from_db()

    with pytest.raises(version_service.DomainError) as excinfo:
        version_service.edit_message(version, 'tarde', editor)

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('B4-L01')
def test_archived_project_rejects_uploads(document, versiona_context):
    from documents.services.trash_service import archive_project

    archive_project(versiona_context.project, versiona_context.users['admin'])
    versiona_context.project.refresh_from_db()
    document.project.refresh_from_db()

    with pytest.raises(version_service.DomainError) as excinfo:
        upload(document, versiona_context.users['editor'])

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
def test_promotion_keeps_captured_bytes_after_staging_replaced(
    document, versiona_context, monkeypatch,
):
    """A reusable PUT token cannot swap the already-validated PDF."""
    editor = versiona_context.users['editor']
    intent = version_service.create_upload_intent(document, editor)
    captured = (TESTDATA / 'contrato_v1.pdf').read_bytes()
    replacement = (TESTDATA / 'contrato_v2.pdf').read_bytes()
    storage_service.put_bytes(intent.key, captured, 'application/pdf')
    read_bytes = storage_service.get_bytes

    monkeypatch.setattr(
        storage_service, 'get_bytes',
        _replace_staging_after_read(read_bytes, intent.key, replacement),
    )

    version, job = version_service.complete_upload(document, intent.upload_id, 'captura', editor)

    assert read_bytes(version.file_key) == captured
    assert version.sha256 == storage_service.sha256_of(captured)
    assert version.size_bytes == len(captured)
    assert job.status == 'done'
    assert version.section_versions.filter(section__stable_key='plazo-de-ejecucion').exists()


@pytest.mark.django_db
def test_promotion_measures_bytes_replaced_after_metadata(
    document, versiona_context, monkeypatch,
):
    """Persisted size comes from the captured PDF rather than older metadata."""
    editor = versiona_context.users['editor']
    intent = version_service.create_upload_intent(document, editor)
    original = (TESTDATA / 'contrato_v1.pdf').read_bytes()
    replacement = (TESTDATA / 'contrato_v2.pdf').read_bytes()
    storage_service.put_bytes(intent.key, original, 'application/pdf')
    object_head = storage_service.head

    monkeypatch.setattr(
        storage_service, 'head',
        _replace_staging_after_read(object_head, intent.key, replacement),
    )

    version, _ = version_service.complete_upload(document, intent.upload_id, 'captura', editor)

    assert storage_service.get_bytes(version.file_key) == replacement
    assert version.sha256 == storage_service.sha256_of(replacement)
    assert version.size_bytes == len(replacement)


@pytest.mark.django_db
@pytest.mark.parametrize(('replacement', 'expected_status'), [
    pytest.param(b'', 400, id='empty'),
    pytest.param(b'%PDF-' + b'x' * (1024 * 1024), 413, id='oversized'),
])
def test_capture_rejects_invalid_size_after_metadata(
    document, versiona_context, monkeypatch, settings, replacement, expected_status,
):
    """A stale successful head cannot authorize an empty/oversized capture."""
    settings.MAX_PDF_SIZE_MB = 1
    editor = versiona_context.users['editor']
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(intent.key, (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf')
    object_head = storage_service.head

    monkeypatch.setattr(
        storage_service, 'head',
        _replace_staging_after_read(object_head, intent.key, replacement),
    )

    with pytest.raises(version_service.DomainError) as exc:
        version_service.complete_upload(document, intent.upload_id, 'rechazada', editor)

    assert exc.value.status_code == expected_status
    assert not DocumentVersion.objects.filter(document=document).exists()
    document.refresh_from_db()
    assert document.latest_number == 0
    assert storage_service.get_bytes(intent.key) == replacement


@pytest.mark.django_db
def test_promotion_write_failure_preserves_staging(
    document, versiona_context, monkeypatch,
):
    """An atomic filesystem failure cannot allocate a version or lose staging."""
    editor = versiona_context.users['editor']
    intent = version_service.create_upload_intent(document, editor)
    payload = (TESTDATA / 'contrato_v1.pdf').read_bytes()
    storage_service.put_bytes(intent.key, payload, 'application/pdf')
    final_key = storage_service.version_key(document, 1)
    provisional = b'previous provisional object'
    storage_service.put_bytes(final_key, provisional, 'application/pdf')

    def unavailable_fsync(_fd):
        raise OSError('private storage write failed')

    monkeypatch.setattr(filesystem.os, 'fsync', unavailable_fsync)

    with pytest.raises(OSError, match='storage write failed'):
        version_service.complete_upload(document, intent.upload_id, 'rechazada', editor)

    assert not DocumentVersion.objects.filter(document=document).exists()
    document.refresh_from_db()
    assert document.latest_number == 0
    assert storage_service.get_bytes(intent.key) == payload
    assert storage_service.get_bytes(final_key) == provisional
    assert list(filesystem.resolve_path(final_key).parent.glob('.tmp-*')) == []


@pytest.mark.django_db
def test_retry_replaces_uncommitted_promotion_after_database_failure(
    document, versiona_context, monkeypatch,
):
    """A failed DB write cannot make the next version reuse a stale binary."""
    editor = versiona_context.users['editor']
    intent = version_service.create_upload_intent(document, editor)
    first = (TESTDATA / 'contrato_v1.pdf').read_bytes()
    retry = (TESTDATA / 'contrato_v2.pdf').read_bytes()
    storage_service.put_bytes(intent.key, first, 'application/pdf')
    create_version = DocumentVersion.objects.create

    def unavailable_database(**_kwargs):
        raise RuntimeError('private database write failed')

    monkeypatch.setattr(DocumentVersion.objects, 'create', unavailable_database)
    with pytest.raises(RuntimeError, match='database write failed'):
        version_service.complete_upload(document, intent.upload_id, 'fallida', editor)
    monkeypatch.setattr(DocumentVersion.objects, 'create', create_version)
    document.refresh_from_db()
    assert document.latest_number == 0
    assert not DocumentVersion.objects.filter(document=document).exists()
    assert storage_service.get_bytes(intent.key) == first
    assert storage_service.get_bytes(storage_service.version_key(document, 1)) == first
    storage_service.put_bytes(intent.key, retry, 'application/pdf')

    version, job = version_service.complete_upload(document, intent.upload_id, 'reintento', editor)

    assert version.number == 1
    assert storage_service.get_bytes(version.file_key) == retry
    assert version.sha256 == storage_service.sha256_of(retry)
    assert version.size_bytes == len(retry)
    assert job.status == 'done'
