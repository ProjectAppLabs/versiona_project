"""Trash eligibility preserves historic evidence with constant database work."""

import pytest
from audit.models import AuditEvent
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from freezegun import freeze_time
from reviews.models import Seal

from documents.models import Document, DocumentVersion
from documents.services import trash_service
from documents.services.version_service import DomainError

MAX_TRASH_ELIGIBILITY_QUERIES = 2


def _seal(version, context):
    return Seal.objects.create(
        document_version=version, reviewer=context.users['reviewer'], covers_all=True,
        signed_payload={}, signature='historic-signature', key_id='historic-key',
        revoked_at=timezone.now(),
    )


@pytest.mark.django_db
def test_document_eligibility_queries_stay_constant_for_50_versions(
    document_with_versions, record_testsuite_property
):
    """A draft history must not add an existence query for each version."""
    one, _ = document_with_versions(1, document_slug='eligibility-one')
    many, _ = document_with_versions(50, document_slug='eligibility-many')

    with CaptureQueriesContext(connection) as one_queries:
        one_protected = trash_service._has_sealed_versions(one)
    with CaptureQueriesContext(connection) as many_queries:
        many_protected = trash_service._has_sealed_versions(many)

    assert one_protected is False
    assert many_protected is False
    assert len(one_queries) == len(many_queries)
    assert len(many_queries) <= MAX_TRASH_ELIGIBILITY_QUERIES
    record_testsuite_property('eligibility_queries_1_version', len(one_queries))
    record_testsuite_property('eligibility_queries_50_versions', len(many_queries))


@pytest.mark.django_db
def test_project_trash_queries_stay_constant_for_50_documents(
    versiona_context, document_with_versions, record_testsuite_property
):
    """Project trash must not scan each document's version history in Python."""
    project = versiona_context.project
    admin = versiona_context.users['admin']
    document_with_versions(1, document_slug='eligibility-project-0')

    with CaptureQueriesContext(connection) as one_queries:
        trash_service.trash_project(project, project.name, admin)
    project.restore()
    for index in range(1, 50):
        document_with_versions(1, document_slug=f'eligibility-project-{index}')
    with CaptureQueriesContext(connection) as many_queries:
        trash_service.trash_project(project, project.name, admin)

    assert len(one_queries) == len(many_queries)
    assert project.is_trashed is True
    record_testsuite_property('trash_queries_1_document', len(one_queries))
    record_testsuite_property('trash_queries_50_documents', len(many_queries))


@pytest.mark.django_db
def test_document_trash_rejects_revoked_seal_on_trashed_version(
    document_with_versions, versiona_context
):
    """A withdrawn historic seal still protects a tombstoned version from trash."""
    document, versions = document_with_versions(2, document_slug='historic-seal')
    _seal(versions[0], versiona_context)
    versions[0].soft_delete(versiona_context.users['admin'])

    with pytest.raises(DomainError) as exc:
        trash_service.trash_document(document, versiona_context.users['admin'])

    assert exc.value.status_code == 409
    assert Document.objects.filter(pk=document.pk).exists()


@pytest.mark.django_db
@freeze_time('2026-10-08 12:00:00')
def test_project_trash_rejects_approved_version_in_trashed_document(
    document_with_versions, versiona_context
):
    """Global approval checks must include tombstoned descendants."""
    document, versions = document_with_versions(1, document_slug='historic-approval')
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
        is_approved=True, deleted_at=timezone.now()
    )
    document.soft_delete(versiona_context.users['admin'])

    with pytest.raises(DomainError) as exc:
        trash_service.trash_project(
            versiona_context.project, versiona_context.project.name,
            versiona_context.users['admin'],
        )

    assert exc.value.status_code == 409
    versiona_context.project.refresh_from_db()
    assert versiona_context.project.is_trashed is False


@pytest.mark.django_db
def test_document_trash_preserves_actor_attribution(
    document_with_versions, versiona_context
):
    """The optimized eligibility check must still record the deleting actor."""
    document, _ = document_with_versions(1, document_slug='trash-attribution')
    admin = versiona_context.users['admin']

    trash_service.trash_document(document, admin)

    document.refresh_from_db()
    event = AuditEvent.objects.get(event_type='document.trashed', object_id_ref=str(document.public_id))
    assert document.deleted_by_id == admin.pk
    assert event.actor_id == admin.pk
    assert event.payload == {'title': document.title}


@pytest.mark.django_db
def test_project_trash_preserves_exact_name_confirmation(versiona_context):
    """A global evidence check must not bypass the destructive-action confirmation."""
    project = versiona_context.project

    with pytest.raises(DomainError, match='nombre exacto'):
        trash_service.trash_project(project, 'wrong-name', versiona_context.users['admin'])

    project.refresh_from_db()
    assert project.is_trashed is False
