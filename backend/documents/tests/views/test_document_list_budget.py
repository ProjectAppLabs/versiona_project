"""Document list metadata is bounded to its page while preserving serializer data."""

import pytest
from checks.models import CheckResult, CheckRun
from django.db import connection
from django.test.utils import CaptureQueriesContext
from reviews.models import ReviewRequest, Seal

from documents.models import Document, DocumentVersion
from documents.serializers import DocumentListSerializer


def _url(context):
    return f'/api/projects/{context.project.public_id}/documents/'


def _add_documents(context, user_model, count, start=0):
    for index in range(start, start + count):
        author = user_model.objects.create_user(email=f'list-author-{index}@versiona.test')
        document = Document.objects.create(
            project=context.project, title=f'Documento {index}', slug=f'list-{index}',
            latest_number=1,
        )
        version = DocumentVersion.objects.create(
            document=document, number=1, author=author, message=f'Mensaje {index}',
            config_version=context.config, sha256=f'{index:064d}', file_key=f'list/{index}.pdf',
        )
        run = CheckRun.objects.create(document_version=version, config_version=context.config)
        CheckResult.objects.create(check_run=run, key='presence', label='Presencia', outcome='pass')
        CheckRun.objects.create(
            document_version=version, config_version=context.config, status=CheckRun.Status.FAILED
        )
        Seal.objects.create(
            document_version=version, reviewer=context.users['reviewer'], covers_all=True,
            signed_payload={}, signature='list-signature', key_id='list-key',
        )
        ReviewRequest.objects.create(document_version=version, requested_by=context.users['editor'])


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['owner', 'reviewer'])
def test_document_list_queries_stay_constant_for_25_documents(
    client_as, versiona_context, django_user_model, role, record_testsuite_property
):
    """Latest version, author, draft state and check summary must not query per document."""
    _add_documents(versiona_context, django_user_model, 1)
    client = client_as(role)
    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(_url(versiona_context))
    _add_documents(versiona_context, django_user_model, 24, start=1)
    expected = DocumentListSerializer(
        Document.objects.filter(project=versiona_context.project).order_by('-updated_at'), many=True
    ).data

    with CaptureQueriesContext(connection) as many_queries:
        many_response = client.get(_url(versiona_context))

    assert one_response.status_code == 200
    assert many_response.status_code == 200
    assert len(one_queries) == len(many_queries)
    assert many_response.data['count'] == 25
    assert many_response.data['results'] == expected
    record_testsuite_property(f'document_list_queries_1_{role}', len(one_queries))
    record_testsuite_property(f'document_list_queries_25_{role}', len(many_queries))


@pytest.mark.django_db
def test_empty_document_list_queries_stay_constant_for_25_documents(
    client_as, versiona_context
):
    """Prepared null versions must not fall back to one latest-version query per empty document."""
    Document.objects.create(project=versiona_context.project, title='Vacío', slug='empty-0')
    client = client_as('viewer')
    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(_url(versiona_context))
    Document.objects.bulk_create([
        Document(project=versiona_context.project, title=f'Vacío {index}', slug=f'empty-{index}')
        for index in range(1, 25)
    ])

    with CaptureQueriesContext(connection) as many_queries:
        many_response = client.get(_url(versiona_context))

    assert one_response.status_code == 200
    assert many_response.status_code == 200
    assert len(one_queries) == len(many_queries)
    assert [row['latest_version'] for row in many_response.data['results']] == [None] * 25


@pytest.mark.django_db
def test_document_list_returns_alive_version_before_latest_tombstone(
    client_as, document_with_versions, versiona_context
):
    """The monotonic latest_number must not force a deleted latest version into the response."""
    _, versions = document_with_versions(2, document_slug='list-tombstone')
    versions[1].soft_delete(versiona_context.users['editor'])

    response = client_as('viewer').get(_url(versiona_context))

    assert response.status_code == 200
    row = response.data['results'][0]
    assert row['latest_number'] == 2
    assert row['latest_version']['number'] == 1


@pytest.mark.django_db
def test_document_list_returns_null_after_all_versions_are_trashed(
    client_as, document_with_versions, versiona_context
):
    """A document with only tombstones remains visible without a latest alive version."""
    _, versions = document_with_versions(1, document_slug='list-all-trashed')
    versions[0].soft_delete(versiona_context.users['editor'])

    response = client_as('viewer').get(_url(versiona_context))

    assert response.status_code == 200
    assert response.data['results'][0]['latest_version'] is None


@pytest.mark.django_db
@pytest.mark.parametrize('analysis_status', ['pending', 'failed'])
def test_document_list_keeps_latest_unready_version(
    client_as, document_with_versions, versiona_context, analysis_status
):
    """Metadata preparation must not replace the latest upload with an older READY version."""
    _, versions = document_with_versions(2, document_slug=f'list-{analysis_status}')
    DocumentVersion.all_objects.filter(pk=versions[1].pk).update(analysis_status=analysis_status)

    response = client_as('viewer').get(_url(versiona_context))

    assert response.status_code == 200
    latest = response.data['results'][0]['latest_version']
    assert latest['number'] == 2
    assert latest['analysis_status'] == analysis_status


@pytest.mark.django_db
def test_document_detail_keeps_unprepared_serializer_fallback(
    client_as, document_with_versions
):
    """Direct document reads still serialize the latest version outside the prepared list."""
    document, _ = document_with_versions(2, document_slug='list-fallback')
    expected = DocumentListSerializer(document).data

    response = client_as('viewer').get(f'/api/documents/{document.public_id}/')

    assert response.status_code == 200
    assert response.data == expected


@pytest.mark.django_db
def test_document_list_keeps_foreign_org_hidden(client_as, versiona_context):
    """Preparing read metadata must leave the existing tenant authorization in place."""
    response = client_as('non_member').get(_url(versiona_context))

    assert response.status_code == 404
