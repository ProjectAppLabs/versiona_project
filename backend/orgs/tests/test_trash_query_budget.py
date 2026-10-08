"""The unified trash list preserves its contents with bounded database work."""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from documents.models import Document, DocumentVersion
from projects.models import Project


def _add_trash_rows(context, user_model, count, start=0):
    rows = []
    deleted_at = datetime(2026, 10, 8, 10, tzinfo=UTC)
    for index in range(start, start + count):
        deleted_by = user_model.objects.create_user(email=f"trash-{index}@versiona.test")
        deletion = {
            "deleted_at": deleted_at + timedelta(seconds=index),
            "deleted_by": deleted_by,
        }
        project = Project.all_objects.create(
            organization=context.org, name=f"Proyecto {index}", slug=f"trash-project-{index}",
            **deletion,
        )
        document = Document.all_objects.create(
            project=context.project, title=f"Documento {index}", slug=f"trash-document-{index}",
            **deletion,
        )
        live_document = Document.objects.create(
            project=context.project, title=f"Vigente {index}", slug=f"live-document-{index}",
        )
        version = DocumentVersion.all_objects.create(
            document=live_document, number=1, author=context.users["editor"],
            config_version=context.config, file_key=f"trash/{index}.pdf", sha256=f"{index:064d}",
            **deletion,
        )
        rows.extend([
            (project, "project", project.name, context.org.name, deleted_by.email),
            (document, "document", document.title, context.project.name, deleted_by.email),
            (version, "version", f"{live_document.title} · v1", context.project.name, deleted_by.email),
        ])
    return rows


@pytest.mark.django_db
def test_trash_query_count_stays_constant_for_25_rows_per_type(
    versiona_context, client_as, django_user_model, record_testsuite_property,
):
    """A populated trash page cannot add database work for each row."""
    _add_trash_rows(versiona_context, django_user_model, 1)
    client = client_as("owner")
    url = f"/api/orgs/{versiona_context.org.public_id}/trash/"
    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(url)
    _add_trash_rows(versiona_context, django_user_model, 24, start=1)

    with CaptureQueriesContext(connection) as many_queries:
        many_response = client.get(url)

    assert one_response.status_code == 200
    assert many_response.status_code == 200
    assert len(many_response.data["results"]) == 75
    assert len(many_queries) == len(one_queries)
    assert len(many_queries) <= 6
    record_testsuite_property("trash_queries_3_items", len(one_queries))
    record_testsuite_property("trash_queries_75_items", len(many_queries))


@pytest.mark.django_db
def test_trash_returns_original_metadata_in_reverse_deletion_order(
    versiona_context, client_as, django_user_model,
):
    """Prefetching preserves the response values and stable newest-first order."""
    rows = _add_trash_rows(versiona_context, django_user_model, 2)
    expected = [
        (str(obj.public_id), kind, name, context, email)
        for obj, kind, name, context, email in sorted(
            rows, key=lambda row: row[0].deleted_at, reverse=True,
        )
    ]

    response = client_as("owner").get(f"/api/orgs/{versiona_context.org.public_id}/trash/")

    assert response.status_code == 200
    assert [
        (row["public_id"], row["type"], row["name"], row["context"], row["deleted_by"])
        for row in response.data["results"]
    ] == expected


@pytest.mark.django_db
def test_trash_omits_descendants_of_a_trashed_project(
    versiona_context, client_as, django_user_model,
):
    """A project in trash represents its descendants instead of duplicating them."""
    rows = _add_trash_rows(versiona_context, django_user_model, 1)
    project = rows[0][0]
    child = Document.all_objects.create(
        project=project, title="Descendiente", slug="descendiente", deleted_at=project.deleted_at,
    )

    response = client_as("owner").get(f"/api/orgs/{versiona_context.org.public_id}/trash/")

    assert response.status_code == 200
    assert str(child.public_id) not in [row["public_id"] for row in response.data["results"]]
    assert len(response.data["results"]) == 3


@pytest.mark.django_db
def test_trash_hides_foreign_organization_from_non_members(versiona_context, client_as):
    """Foreign users cannot discover the organization's trash."""
    response = client_as("non_member").get(f"/api/orgs/{versiona_context.org.public_id}/trash/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_trash_rejects_regular_organization_members(versiona_context, client_as):
    """Ordinary organization members cannot enter the admin-only trash."""
    response = client_as("viewer").get(f"/api/orgs/{versiona_context.org.public_id}/trash/")

    assert response.status_code == 403
