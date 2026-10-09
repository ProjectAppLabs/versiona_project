"""Trash rules (kit 3 — B4/C4, tensions T4/T5). Scenario ids per docs/audit/03."""

from pathlib import Path

import pytest
from freezegun import freeze_time
from reviews.models import Seal

from documents.models import Document, DocumentVersion
from documents.services import storage_service, trash_service, version_service
from documents.services.version_service import DomainError

TESTDATA = Path(__file__).resolve().parents[4] / 'testdata' / 'pdfs'


def upload(document, fixture, message, author):
    """Upload a PDF fixture through the complete analyzed-version lifecycle."""
    intent = version_service.create_upload_intent(document, author)
    storage_service.put_bytes(intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf')
    version, _ = version_service.complete_upload(document, intent.upload_id, message, author)
    return version


@pytest.fixture
def doc_and_version(document_with_versions):
    """Build a document with a single draft version for trash tests."""
    document, versions = document_with_versions(n_versions=1)
    return document, versions[0]


@pytest.mark.django_db
@pytest.mark.escenario('C4-F01')
def test_latest_draft_version_goes_to_trash(doc_and_version, versiona_context):
    """Catches soft_delete() dropping actor attribution.

    E.g. a call-site that forgets to pass `user`: a bare is_trashed check only
    proves deleted_at is set, not who trashed it (core/models/soft_delete.py:72-75).
    """
    document, version = doc_and_version

    trash_service.trash_version(version, versiona_context.users['editor'])

    assert DocumentVersion.objects.filter(pk=version.pk).count() == 0
    trashed = DocumentVersion.all_objects.get(pk=version.pk)
    assert trashed.deleted_at is not None
    assert trashed.deleted_by_id == versiona_context.users['editor'].pk


@pytest.mark.django_db
@pytest.mark.escenario('C4-E01')
def test_approved_version_is_never_trash_eligible(doc_and_version, versiona_context):
    """trash_version rejects an approved version with a 409 conflict."""
    document, version = doc_and_version
    DocumentVersion.all_objects.filter(pk=version.pk).update(is_approved=True)
    version.refresh_from_db()

    with pytest.raises(DomainError) as excinfo:
        trash_service.trash_version(version, versiona_context.users['admin'])

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('C4-E02')
def test_non_latest_version_cannot_be_trashed(document_with_versions, versiona_context):
    """trash_version rejects a non-latest version with a 409 conflict."""
    document, versions = document_with_versions(n_versions=2)

    with pytest.raises(DomainError) as excinfo:
        trash_service.trash_version(versions[0], versiona_context.users['editor'])

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
def test_correct_upload_after_trashing_a_wrong_file_reaches_ready(versiona_context):
    """Catches: sections retired by a trashed wrong upload blocking the analysis
    of the corrected delivery (C4 recovery path)."""
    editor = versiona_context.users['editor']
    document = version_service.create_document(versiona_context.project, 'Entrega corregida', editor)
    upload(document, 'contrato_v1.pdf', 'v1', editor)
    wrong = upload(document, 'sin_encabezados.pdf', 'archivo equivocado', editor)
    trash_service.trash_version(wrong, editor)

    corrected = upload(document, 'contrato_v2.pdf', 'entrega correcta', editor)

    corrected.refresh_from_db()
    assert corrected.analysis_status == DocumentVersion.AnalysisStatus.READY


@pytest.mark.django_db
@pytest.mark.escenario('C4-F02')
def test_restore_returns_version_to_timeline(doc_and_version, versiona_context):
    """restore_version brings a trashed version back into the alive queryset."""
    document, version = doc_and_version
    trash_service.trash_version(version, versiona_context.users['editor'])
    version.refresh_from_db()

    trash_service.restore_version(version, versiona_context.users['editor'])

    assert DocumentVersion.objects.filter(pk=version.pk).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('C4-E03')
def test_restore_blocked_when_newer_version_exists(document_with_versions, versiona_context):
    """restore_version is rejected with 409 when a newer version already exists."""
    document, versions = document_with_versions(n_versions=1)
    trash_service.trash_version(versions[0], versiona_context.users['editor'])
    DocumentVersion.objects.create(
        document=document, number=2, sha256='b' * 64,
        file_key='test/x/v2/original.pdf',
        analysis_status=DocumentVersion.AnalysisStatus.READY,
        config_version=versiona_context.config,
    )
    document.latest_number = 2
    document.save(update_fields=['latest_number'])
    versions[0].refresh_from_db()

    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_version(versions[0], versiona_context.users['editor'])

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('C4-A01')
def test_purge_removes_expired_and_number_is_never_reused(doc_and_version, versiona_context, settings):
    """purge_expired deletes a version past the grace window; the document's latest_number is never reused (I1)."""
    settings.TRASH_RETENTION_DAYS = 30
    document, version = doc_and_version
    with freeze_time('2026-06-01'):
        trash_service.trash_version(version, versiona_context.users['editor'])

    with freeze_time('2026-07-05'):
        counts = trash_service.purge_expired()

    assert counts['versions'] == 1
    assert DocumentVersion.all_objects.filter(pk=version.pk).count() == 0
    # I1 tombstone: latest_number never decreases → next upload is v2
    document.refresh_from_db()
    assert document.latest_number == 1


@pytest.mark.django_db
@pytest.mark.escenario('B4-F02')
def test_trash_project_requires_exact_name_confirmation(versiona_context):
    """trash_project rejects a confirmation name that does not match exactly."""
    with pytest.raises(DomainError, match='nombre exacto'):
        trash_service.trash_project(
            versiona_context.project, 'nombre-equivocado', versiona_context.users['admin']
        )


@pytest.mark.django_db
@pytest.mark.escenario('B4-E01')
def test_project_with_approved_version_only_archivable(document_with_versions, versiona_context):
    """trash_project rejects a project holding an approved version with a 409 conflict."""
    document, versions = document_with_versions(n_versions=1)
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(is_approved=True)

    with pytest.raises(DomainError) as excinfo:
        trash_service.trash_project(
            versiona_context.project, versiona_context.project.name,
            versiona_context.users['admin'],
        )

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('B4-F01')
def test_archive_makes_project_read_only_and_reversible(versiona_context):
    """archive_project/unarchive_project toggle the project's is_read_only flag."""
    admin = versiona_context.users['admin']

    trash_service.archive_project(versiona_context.project, admin)
    versiona_context.project.refresh_from_db()
    assert versiona_context.project.is_read_only is True

    trash_service.unarchive_project(versiona_context.project, admin)
    versiona_context.project.refresh_from_db()
    assert versiona_context.project.is_read_only is False


@pytest.mark.django_db
@pytest.mark.escenario('C4-F01')
def test_trash_document_without_sealed_versions_goes_to_trash(doc_and_version, versiona_context):
    """Catches soft_delete() dropping actor attribution.

    E.g. a call-site that forgets to pass `user`: a bare is_trashed check only
    proves deleted_at is set, not who trashed it (core/models/soft_delete.py:72-75).
    """
    document, version = doc_and_version

    trash_service.trash_document(document, versiona_context.users['admin'])

    assert Document.objects.filter(pk=document.pk).count() == 0
    trashed = Document.all_objects.get(pk=document.pk)
    assert trashed.deleted_at is not None
    assert trashed.deleted_by_id == versiona_context.users['admin'].pk


@pytest.mark.django_db
@pytest.mark.escenario('C4-E01')
def test_document_with_sealed_version_cannot_be_trashed(doc_and_version, versiona_context):
    """trash_document rejects a document with a sealed version with a 409 conflict."""
    document, version = doc_and_version
    Seal.objects.create(
        document_version=version, reviewer=versiona_context.users['reviewer'],
        covers_all=True, signed_payload={}, signature='firma', key_id='k-test',
    )

    with pytest.raises(DomainError) as excinfo:
        trash_service.trash_document(document, versiona_context.users['admin'])

    assert excinfo.value.status_code == 409
    assert 'archiva el proyecto' in str(excinfo.value)


@pytest.mark.django_db
@pytest.mark.escenario('C4-F02')
def test_restore_version_not_in_trash_is_rejected(doc_and_version, versiona_context):
    """restore_version rejects a version that is not currently trashed with a 400."""
    document, version = doc_and_version

    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_version(version, versiona_context.users['editor'])

    assert excinfo.value.status_code == 400
    assert str(excinfo.value) == 'La versión no está en la papelera.'


@pytest.mark.django_db
@pytest.mark.escenario('C4-E03')
def test_restore_version_requires_restoring_trashed_document_first(doc_and_version, versiona_context):
    """restore_version is rejected with 409 while the parent document is still trashed."""
    document, version = doc_and_version
    editor = versiona_context.users['editor']
    trash_service.trash_version(version, editor)
    version.refresh_from_db()
    trash_service.trash_document(document, versiona_context.users['admin'])

    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_version(version, editor)

    assert excinfo.value.status_code == 409
    assert str(excinfo.value) == 'Restaura primero el documento/proyecto contenedor.'


@pytest.mark.django_db
@pytest.mark.escenario('C4-F02')
def test_restore_document_not_in_trash_is_rejected(doc_and_version, versiona_context):
    """restore_document rejects a document that is not currently trashed with a 400."""
    document, _ = doc_and_version

    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_document(document, versiona_context.users['admin'])

    assert excinfo.value.status_code == 400
    assert str(excinfo.value) == 'El documento no está en la papelera.'


@pytest.mark.django_db
@pytest.mark.escenario('B4-F03')
def test_restore_document_requires_restoring_project_first(doc_and_version, versiona_context):
    """restore_document is rejected with 409 while the parent project is still trashed."""
    document, _ = doc_and_version
    admin = versiona_context.users['admin']
    trash_service.trash_document(document, admin)
    trash_service.trash_project(versiona_context.project, versiona_context.project.name, admin)

    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_document(document, admin)

    assert excinfo.value.status_code == 409
    assert str(excinfo.value) == 'Restaura primero el proyecto.'


@pytest.mark.django_db
@pytest.mark.escenario('C4-F02')
def test_restore_document_returns_it_to_the_project(doc_and_version, versiona_context):
    """restore_document brings a trashed document back into the alive queryset."""
    document, _ = doc_and_version
    admin = versiona_context.users['admin']
    trash_service.trash_document(document, admin)

    trash_service.restore_document(document, admin)

    document.refresh_from_db()
    assert document.is_trashed is False
    assert Document.objects.filter(pk=document.pk).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('B4-F03')
def test_restore_project_not_in_trash_is_rejected(versiona_context):
    """restore_project rejects a project that is not currently trashed with a 400."""
    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_project(versiona_context.project, versiona_context.users['admin'])

    assert excinfo.value.status_code == 400
    assert str(excinfo.value) == 'El proyecto no está en la papelera.'


@pytest.mark.django_db
@pytest.mark.escenario('B4-A02')
def test_purge_deletes_expired_document_with_its_versions(doc_and_version, versiona_context, settings):
    """purge_expired deletes an expired document together with its versions."""
    settings.TRASH_RETENTION_DAYS = 30
    document, version = doc_and_version
    with freeze_time('2026-06-01'):
        trash_service.trash_document(document, versiona_context.users['admin'])

    with freeze_time('2026-07-05'):
        counts = trash_service.purge_expired()

    assert counts == {'versions': 0, 'documents': 1, 'projects': 0}
    assert Document.all_objects.filter(pk=document.pk).count() == 0
    assert DocumentVersion.all_objects.filter(pk=version.pk).count() == 0


@pytest.mark.django_db
@pytest.mark.escenario('B4-A02')
def test_purge_deletes_expired_project_cascade(doc_and_version, versiona_context, settings):
    """purge_expired deletes an expired project cascading to its documents and versions."""
    from projects.models import Project

    settings.TRASH_RETENTION_DAYS = 30
    document, version = doc_and_version
    with freeze_time('2026-06-01'):
        trash_service.trash_project(
            versiona_context.project, versiona_context.project.name,
            versiona_context.users['admin'],
        )

    with freeze_time('2026-07-05'):
        counts = trash_service.purge_expired()

    assert counts == {'versions': 0, 'documents': 0, 'projects': 1}
    assert Project.all_objects.filter(pk=versiona_context.project.pk).count() == 0
    assert Document.all_objects.filter(pk=document.pk).count() == 0
    assert DocumentVersion.all_objects.filter(pk=version.pk).count() == 0


@pytest.mark.django_db
@pytest.mark.escenario('B4-E02')
def test_project_restore_with_live_slug_collision_is_rejected(versiona_context):
    """restore_project is rejected with 409 when an alive project already holds the same slug."""
    from projects.models import Project

    admin = versiona_context.users['admin']
    trash_service.trash_project(versiona_context.project, versiona_context.project.name, admin)
    versiona_context.project.refresh_from_db()
    Project.objects.create(
        organization=versiona_context.org, name='Torre Central', slug='torre-central'
    )

    with pytest.raises(DomainError) as excinfo:
        trash_service.restore_project(versiona_context.project, admin)

    assert excinfo.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('B4-F03')
def test_restore_document_renames_slug_when_an_alive_document_took_it(
    doc_and_version, versiona_context
):
    """restore_document appends '-restaurado' to the slug when an alive document has taken it."""
    document, _ = doc_and_version
    original_slug = document.slug
    trash_service.trash_document(document, versiona_context.users['editor'])
    Document.objects.create(
        project=document.project, title=document.title, slug=original_slug
    )

    trash_service.restore_document(
        Document.all_objects.get(pk=document.pk), versiona_context.users['editor']
    )

    restored = Document.objects.get(pk=document.pk)
    assert restored.slug == f'{original_slug}-restaurado'
    assert Document.objects.filter(slug=original_slug).count() == 1
