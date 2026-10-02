"""Keyset traversal contracts for physical trash purging."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test.utils import CaptureQueriesContext
from projects.models import Project
from reviews.models import Certificate

from documents.models import Document, DocumentVersion
from documents.services import trash_service

EXPIRED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
PURGE_NOW = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _create_document(versiona_context, slug):
    return Document.objects.create(
        project=versiona_context.project,
        title=slug.replace('-', ' ').title(),
        slug=slug,
    )


def _create_versions(versiona_context, document, amount, key_prefix):
    DocumentVersion.objects.bulk_create([
        DocumentVersion(
            document=document,
            number=number,
            message=f'{key_prefix} {number}',
            sha256=f'{number:064x}',
            file_key=f'test/{key_prefix}/{number}.pdf',
            analysis_status=DocumentVersion.AnalysisStatus.READY,
            config_version=versiona_context.config,
            author=versiona_context.users['editor'],
        )
        for number in range(1, amount + 1)
    ])
    document.latest_number = amount
    document.save(update_fields=['latest_number'])
    return list(
        DocumentVersion.all_objects.filter(document=document)
        .order_by('pk')
        .values_list('pk', flat=True)
    )


def _create_documents_with_versions(versiona_context, amount, key_prefix):
    Document.objects.bulk_create([
        Document(
            project=versiona_context.project,
            title=f'{key_prefix} {number}',
            slug=f'{key_prefix}-{number}',
            latest_number=1,
        )
        for number in range(1, amount + 1)
    ])
    documents = list(
        Document.all_objects.filter(
            project=versiona_context.project,
            slug__startswith=f'{key_prefix}-',
        ).order_by('pk')
    )
    DocumentVersion.objects.bulk_create([
        DocumentVersion(
            document=document,
            number=1,
            message=f'{key_prefix} version',
            sha256=f'{number:064x}',
            file_key=f'test/{key_prefix}/{number}.pdf',
            analysis_status=DocumentVersion.AnalysisStatus.READY,
            config_version=versiona_context.config,
            author=versiona_context.users['editor'],
        )
        for number, document in enumerate(documents, start=1)
    ])
    document_pks = [document.pk for document in documents]
    version_pks = list(
        DocumentVersion.all_objects.filter(document_id__in=document_pks)
        .order_by('pk')
        .values_list('pk', flat=True)
    )
    return document_pks, version_pks


def _bounded_candidates(queries, table_name, filter_fragment):
    table_fragment = f'from `{table_name}`'
    return [
        query['sql'].lower()
        for query in queries.captured_queries
        if 'select' in query['sql'].lower()
        and table_fragment in query['sql'].lower()
        and filter_fragment in query['sql'].lower()
        and 'limit 100' in query['sql'].lower()
    ]


def _assert_three_data_pages(candidates, omitted_column):
    assert len(candidates) == 4
    assert all(
        'id' in candidate
        and 'deleted_at' in candidate
        and omitted_column not in candidate
        for candidate in candidates
    )
    assert '`id` >' in candidates[1]


@pytest.mark.django_db
def test_purge_removes_every_expired_version_across_keyset_pages(versiona_context):
    """Fails if deleting earlier pages makes keyset purge skip later versions."""
    # Arrange
    document = _create_document(versiona_context, 'version-page-root')
    version_pks = _create_versions(versiona_context, document, 201, 'version-page')
    DocumentVersion.all_objects.filter(pk__in=version_pks).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        counts = trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(
        queries,
        'documents_documentversion',
        'deleted_at',
    )

    # Assert
    assert counts == {'versions': 201, 'documents': 0, 'projects': 0}
    assert DocumentVersion.all_objects.filter(pk__in=version_pks).count() == 0
    _assert_three_data_pages(candidates, 'file_key')


@pytest.mark.django_db
def test_purge_removes_every_expired_document_across_keyset_pages(versiona_context):
    """Fails if document candidate pagination skips rows after earlier deletions."""
    # Arrange
    document_pks, version_pks = _create_documents_with_versions(
        versiona_context,
        201,
        'document-page',
    )
    Document.all_objects.filter(pk__in=document_pks).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        counts = trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(queries, 'documents_document', 'deleted_at')

    # Assert
    assert counts == {'versions': 0, 'documents': 201, 'projects': 0}
    assert Document.all_objects.filter(pk__in=document_pks).count() == 0
    assert DocumentVersion.all_objects.filter(pk__in=version_pks).count() == 0
    _assert_three_data_pages(candidates, 'title')


@pytest.mark.django_db
def test_document_purge_removes_descendant_versions_across_keyset_pages(versiona_context):
    """Fails if a document's inner version traversal skips a later keyset page."""
    # Arrange
    document = _create_document(versiona_context, 'document-version-page-root')
    version_pks = _create_versions(versiona_context, document, 201, 'document-version-page')
    Document.all_objects.filter(pk=document.pk).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        counts = trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(
        queries,
        'documents_documentversion',
        'document_id',
    )

    # Assert
    assert counts == {'versions': 0, 'documents': 1, 'projects': 0}
    assert Document.all_objects.filter(pk=document.pk).count() == 0
    assert DocumentVersion.all_objects.filter(pk__in=version_pks).count() == 0
    _assert_three_data_pages(candidates, 'file_key')


@pytest.mark.django_db
def test_project_purge_removes_descendant_documents_across_keyset_pages(versiona_context):
    """Fails if project cleanup skips descendant document pages after deletion."""
    # Arrange
    document_pks, version_pks = _create_documents_with_versions(
        versiona_context,
        201,
        'project-document-page',
    )
    Project.all_objects.filter(pk=versiona_context.project.pk).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        counts = trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(queries, 'documents_document', 'project_id')

    # Assert
    assert counts == {'versions': 0, 'documents': 0, 'projects': 1}
    assert Project.all_objects.filter(pk=versiona_context.project.pk).count() == 0
    assert Document.all_objects.filter(pk__in=document_pks).count() == 0
    assert DocumentVersion.all_objects.filter(pk__in=version_pks).count() == 0
    _assert_three_data_pages(candidates, 'title')


@pytest.mark.django_db
def test_repeated_purge_returns_empty_counts(versiona_context):
    """Fails if a completed purge retains cursor state or reports stale candidates."""
    # Arrange
    document = _create_document(versiona_context, 'repeat-purge-root')
    version_pks = _create_versions(versiona_context, document, 1, 'repeat-purge')
    DocumentVersion.all_objects.filter(pk__in=version_pks).update(deleted_at=EXPIRED_AT)
    trash_service.purge_expired(now=PURGE_NOW)

    # Act
    counts = trash_service.purge_expired(now=PURGE_NOW)

    # Assert
    assert counts == {'versions': 0, 'documents': 0, 'projects': 0}


@pytest.mark.django_db
def test_purge_preserves_a_version_referenced_by_a_certificate(versiona_context):
    """Fails if physical purge bypasses PROTECT and destroys certificate evidence."""
    # Arrange
    document = _create_document(versiona_context, 'certificate-protection-root')
    version_pks = _create_versions(versiona_context, document, 1, 'certificate-protection')
    version = DocumentVersion.all_objects.get(pk=version_pks[0])
    certificate = Certificate.objects.create(
        organization=versiona_context.org,
        document_version=version,
        issued_by=versiona_context.users['admin'],
        serial='CERT-PURGE-0001',
        snapshot={'version': version.number},
        pdf_key='certificates/purge-protection.pdf',
    )
    DocumentVersion.all_objects.filter(pk=version.pk).update(deleted_at=EXPIRED_AT)

    # Act
    with pytest.raises(ProtectedError):
        trash_service.purge_expired(now=PURGE_NOW)

    # Assert
    assert Certificate.objects.filter(pk=certificate.pk).count() == 1
    assert DocumentVersion.all_objects.filter(pk=version.pk).count() == 1


@pytest.mark.django_db
def test_purge_version_candidate_query_limits_rows_to_one_hundred(versiona_context):
    """Fails if purge removes the bounded candidate projection or its 100-row limit."""
    # Arrange
    document = _create_document(versiona_context, 'projection-page-root')
    version_pks = _create_versions(versiona_context, document, 101, 'projection-page')
    DocumentVersion.all_objects.filter(pk__in=version_pks).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(
        queries,
        'documents_documentversion',
        'deleted_at',
    )

    # Assert
    assert len(candidates) == 3
    assert 'id' in candidates[0]
    assert 'deleted_at' in candidates[0]
    assert 'file_key' not in candidates[0]
    assert 'sha256' not in candidates[0]
    assert 'id' in candidates[1]
    assert '>' in candidates[1]


@pytest.mark.django_db
def test_project_purge_removes_descendant_versions_across_keyset_pages(versiona_context):
    """Fails if a project's inner version traversal skips a later keyset page."""
    # Arrange
    document = _create_document(versiona_context, 'project-version-page-root')
    version_pks = _create_versions(versiona_context, document, 201, 'project-version-page')
    Project.all_objects.filter(pk=versiona_context.project.pk).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        counts = trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(
        queries,
        'documents_documentversion',
        'document_id',
    )

    # Assert
    assert counts == {'versions': 0, 'documents': 0, 'projects': 1}
    assert DocumentVersion.all_objects.filter(pk__in=version_pks).count() == 0
    _assert_three_data_pages(candidates, 'file_key')


@pytest.mark.django_db
def test_purge_removes_expired_projects_across_keyset_pages(versiona_context):
    """Fails if root project candidate pagination skips later expired projects."""
    # Arrange
    Project.objects.bulk_create([
        Project(
            organization=versiona_context.org,
            name=f'Purge Project {number}',
            slug=f'purge-project-{number}',
        )
        for number in range(1, 202)
    ])
    project_pks = list(
        Project.all_objects.filter(
            organization=versiona_context.org,
            slug__startswith='purge-project-',
        ).order_by('pk').values_list('pk', flat=True)
    )
    Project.all_objects.filter(pk__in=project_pks).update(deleted_at=EXPIRED_AT)

    # Act
    with CaptureQueriesContext(connection) as queries:
        counts = trash_service.purge_expired(now=PURGE_NOW)
    candidates = _bounded_candidates(queries, 'projects_project', 'deleted_at')

    # Assert
    assert counts == {'versions': 0, 'documents': 0, 'projects': 201}
    assert Project.all_objects.filter(pk__in=project_pks).count() == 0
    _assert_three_data_pages(candidates, 'name')
