"""Regression budgets for the document version timeline."""

import pytest
from checks.models import CheckResult, CheckRun
from django.db import connection
from django.test.utils import CaptureQueriesContext
from freezegun import freeze_time
from reviews.models import ReviewRequest, Seal

from documents.models import Document, DocumentVersion
from documents.serializers import VersionListSerializer

MAX_VERSION_LIST_QUERIES = 6


def _timeline_url(document):
    return f"/api/documents/{document.public_id}/versions/"


def _timeline_item(response, number):
    return next(item for item in response.data["results"] if item["number"] == number)


def _create_check_run(version, status, created_at, outcomes=()):
    with freeze_time(created_at):
        run = CheckRun.objects.create(
            document_version=version,
            config_version=version.config_version,
            status=status,
        )
        CheckResult.objects.bulk_create(
            [
                CheckResult(
                    check_run=run,
                    key=f"{outcome}-{index}",
                    label=f"Resultado {outcome}",
                    outcome=outcome,
                )
                for index, outcome in enumerate(outcomes, start=1)
            ]
        )
    return run


def _create_timeline_version(document, number, config_version, author):
    return DocumentVersion.objects.create(
        document=document,
        number=number,
        message=f"versión {number}",
        sha256=f"{number:064d}",
        file_key=f"test/docs/{document.public_id}/v{number}/original.pdf",
        analysis_status=DocumentVersion.AnalysisStatus.READY,
        config_version=config_version,
        author=author,
    )


@pytest.mark.django_db
def test_timeline_query_count_stays_constant_from_one_to_25_versions(
    client_as, document_with_versions
):
    """Falla si el timeline vuelve a consultar autor, sellos, revisiones o checks por fila."""
    one_document, _ = document_with_versions(1, document_slug="timeline-one")
    many_document, _ = document_with_versions(25, document_slug="timeline-twenty-five")
    client = client_as("viewer")

    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(_timeline_url(one_document))

    with CaptureQueriesContext(connection) as many_queries:
        many_response = client.get(_timeline_url(many_document))

    assert one_response.status_code == 200
    assert many_response.status_code == 200
    assert len(one_queries) == len(many_queries)
    assert len(many_queries) <= MAX_VERSION_LIST_QUERIES
    assert many_response.data["count"] == 25


@pytest.mark.django_db
def test_timeline_limits_results_to_fixed_page_size(client_as, document_with_versions):
    """Falla si page_size permite devolver más de las 25 versiones fijadas por el contrato."""
    document, _ = document_with_versions(26, document_slug="timeline-fixed-page")

    response = client_as("viewer").get(f"{_timeline_url(document)}?page_size=100")

    assert response.status_code == 200
    assert response.data["count"] == 26
    assert len(response.data["results"]) == 25


@pytest.fixture
def annotated_timeline(client_as, versiona_context):
    """Build versions that exercise every annotation emitted by the timeline."""
    document = Document.objects.create(
        project=versiona_context.project,
        title="Timeline Metadata",
        slug="timeline-metadata",
    )
    reviewer = versiona_context.users["reviewer"]
    editor = versiona_context.users["editor"]
    config = versiona_context.config
    versions = [
        _create_timeline_version(document, 1, config, reviewer),
        _create_timeline_version(document, 2, config, editor),
        _create_timeline_version(document, 3, config, editor),
        _create_timeline_version(document, 4, config, editor),
        _create_timeline_version(document, 5, config, editor),
        _create_timeline_version(document, 6, config, editor),
        _create_timeline_version(document, 7, config, None),
        _create_timeline_version(document, 8, config, editor),
        _create_timeline_version(document, 9, config, editor),
    ]
    document.latest_number = 9
    document.save(update_fields=["latest_number"])

    seal = Seal.objects.create(
        document_version=versions[1],
        reviewer=reviewer,
        covers_all=True,
        signed_payload={"version": 2},
        signature="revoked-signature",
        key_id="revoked-key",
    )
    seal.revoked_at = versions[1].created_at
    seal.save(update_fields=["revoked_at"])
    ReviewRequest.objects.create(
        document_version=versions[2],
        requested_by=versiona_context.users["editor"],
        status=ReviewRequest.Status.CANCELLED,
    )
    _create_check_run(
        versions[3], CheckRun.Status.DONE, "2026-09-30 09:00:00", ("fail", "fail")
    )
    _create_check_run(
        versions[3],
        CheckRun.Status.DONE,
        "2026-09-30 10:00:00",
        ("pass", "warn", "fail"),
    )
    _create_check_run(versions[3], CheckRun.Status.FAILED, "2026-09-30 11:00:00")
    _create_check_run(versions[4], CheckRun.Status.DONE, "2026-09-30 10:00:00")
    _create_check_run(versions[5], CheckRun.Status.FAILED, "2026-09-30 10:00:00")
    versions[7].soft_delete(versiona_context.users["editor"])
    ReviewRequest.objects.create(
        document_version=versions[8],
        requested_by=versiona_context.users["editor"],
        status=ReviewRequest.Status.OPEN,
    )

    return client_as("viewer").get(_timeline_url(document))


@pytest.mark.django_db
def test_timeline_returns_author_email_for_distinct_author(annotated_timeline):
    """Falla si el timeline deja de cargar el autor de cada versión sin una consulta por fila."""
    assert annotated_timeline.status_code == 200
    assert (
        _timeline_item(annotated_timeline, 1)["author_email"]
        == "reviewer@versiona.test"
    )


@pytest.mark.django_db
def test_timeline_marks_revoked_seal_version_not_draft(annotated_timeline):
    """Falla si una versión con sello revocado recupera el estado de borrador."""
    assert _timeline_item(annotated_timeline, 2)["is_draft"] is False


@pytest.mark.django_db
def test_timeline_keeps_cancelled_review_version_draft(annotated_timeline):
    """Falla si una revisión cancelada sigue bloqueando el borrador de la versión."""
    assert _timeline_item(annotated_timeline, 3)["is_draft"] is True


@pytest.mark.django_db
def test_timeline_marks_open_review_version_not_draft(annotated_timeline):
    """Falla si una revisión abierta deja de bloquear el borrador de la versión."""
    assert _timeline_item(annotated_timeline, 9)["is_draft"] is False


@pytest.mark.django_db
def test_timeline_uses_latest_done_check_summary(annotated_timeline):
    """Falla si un run FAILED posterior oculta el resumen del último run DONE."""
    assert _timeline_item(annotated_timeline, 4)["check_summary"] == {
        "pass": 1,
        "warn": 1,
        "fail": 1,
    }


@pytest.mark.django_db
def test_timeline_returns_zero_summary_for_done_run_without_results(annotated_timeline):
    """Falla si un run DONE vacío deja de devolver los tres contadores explícitos."""
    assert _timeline_item(annotated_timeline, 5)["check_summary"] == {
        "pass": 0,
        "warn": 0,
        "fail": 0,
    }


@pytest.mark.django_db
def test_timeline_returns_null_summary_without_done_run(annotated_timeline):
    """Falla si un run FAILED se presenta como resumen válido en el timeline."""
    assert _timeline_item(annotated_timeline, 6)["check_summary"] is None


@pytest.mark.django_db
def test_timeline_returns_null_for_missing_author(annotated_timeline):
    """Falla si una versión histórica sin autor expone un valor inventado."""
    assert _timeline_item(annotated_timeline, 7)["author_email"] is None


@pytest.mark.django_db
def test_timeline_includes_tombstoned_version(annotated_timeline):
    """Falla si el timeline excluye el tombstone que la papelera debe mostrar."""
    assert _timeline_item(annotated_timeline, 8)["is_trashed"] is True


@pytest.mark.django_db
def test_unannotated_version_serializer_uses_model_draft_rule(
    document_with_versions, versiona_context
):
    """Falla si el fallback deja de reconocer un sello revocado al serializar fuera del timeline."""
    _, versions = document_with_versions(1, document_slug="serializer-draft-fallback")
    seal = Seal.objects.create(
        document_version=versions[0],
        reviewer=versiona_context.users["reviewer"],
        covers_all=True,
        signed_payload={"version": 1},
        signature="fallback-signature",
        key_id="fallback-key",
    )
    seal.revoked_at = versions[0].created_at
    seal.save(update_fields=["revoked_at"])

    payload = VersionListSerializer(versions[0]).data

    assert payload["is_draft"] is False


@pytest.mark.django_db
def test_unannotated_version_serializer_uses_check_summary(document_with_versions):
    """Falla si el fallback deja de entregar el resumen de checks fuera del queryset anotado."""
    _, versions = document_with_versions(1, document_slug="serializer-summary-fallback")
    _create_check_run(
        versions[0],
        CheckRun.Status.DONE,
        "2026-09-30 10:00:00",
        ("pass", "warn", "warn"),
    )

    payload = VersionListSerializer(versions[0]).data

    assert payload["check_summary"] == {"pass": 1, "warn": 2, "fail": 0}
