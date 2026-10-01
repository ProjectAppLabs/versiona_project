"""Regression budgets for public comparison TTL cleanup."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from documents.services import storage_service
from freezegun import freeze_time

from public_tools.models import PublicComparison
from public_tools.services.public_comparison_service import storage_key_for
from public_tools.tasks import purge_expired_public_comparisons


def _expired_comparisons(count, expires_at):
    statuses = (
        PublicComparison.Status.DONE,
        PublicComparison.Status.FAILED,
        PublicComparison.Status.PENDING,
    )
    return PublicComparison.objects.bulk_create(
        [
            PublicComparison(
                status=statuses[index % len(statuses)],
                result={"payload": "x" * 4096, "index": index},
                expires_at=expires_at,
            )
            for index in range(count)
        ]
    )


def _expiration_select_queries(queries):
    return [
        entry["sql"]
        for entry in queries
        if entry["sql"].lstrip().upper().startswith("SELECT")
        and "public_tools_publiccomparison" in entry["sql"]
    ]


@pytest.mark.django_db
@freeze_time("2026-09-30 12:00:00")
def test_purge_uses_bounded_keyset_selection():
    """Falla si la purga materializa JSON completo o selecciona más de 100 filas por lote."""
    expired = _expired_comparisons(201, timezone.now() - timedelta(seconds=1))
    expired_ids = [comparison.pk for comparison in expired]

    with CaptureQueriesContext(connection) as queries:
        purged = purge_expired_public_comparisons()

    fetches = _expiration_select_queries(queries.captured_queries)

    assert purged == 201
    assert PublicComparison.objects.filter(pk__in=expired_ids).count() == 0
    assert len(fetches) == 4
    assert all("LIMIT 100" in query for query in fetches)
    assert all("result" not in query.lower() for query in fetches)


@pytest.mark.django_db
@freeze_time("2026-09-30 12:00:00")
def test_purge_removes_storage_keys_for_expired_comparison():
    """Falla si una comparación vencida se borra sin limpiar cualquiera de sus dos archivos."""
    comparison = PublicComparison.objects.create(
        status=PublicComparison.Status.DONE,
        result={"status": "done"},
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    key_a = storage_key_for(comparison.public_id, "a")
    key_b = storage_key_for(comparison.public_id, "b")
    storage_service.put_bytes(key_a, b"a", "application/pdf")
    storage_service.put_bytes(key_b, b"b", "application/pdf")

    purged = purge_expired_public_comparisons()

    assert purged == 1
    assert PublicComparison.objects.filter(pk=comparison.pk).count() == 0
    assert storage_service.head(key_a) is None
    assert storage_service.head(key_b) is None


@pytest.mark.django_db
@freeze_time("2026-09-30 12:00:00")
@pytest.mark.parametrize(
    "offset", [timedelta(), timedelta(minutes=1)], ids=("cutoff", "future")
)
def test_purge_retains_comparison_at_or_after_cutoff(offset):
    """Falla si la comparación situada en el corte exacto o en el futuro se elimina antes de tiempo."""
    comparison = PublicComparison.objects.create(
        status=PublicComparison.Status.PENDING,
        result={"status": "pending"},
        expires_at=timezone.now() + offset,
    )

    purged = purge_expired_public_comparisons()

    assert purged == 0
    assert PublicComparison.objects.filter(pk=comparison.pk).count() == 1


@pytest.mark.django_db
@freeze_time("2026-09-30 12:00:00")
def test_purge_returns_zero_after_expired_comparisons_are_removed():
    """Falla si una segunda ejecución vuelve a contar comparaciones ya purgadas."""
    _expired_comparisons(201, timezone.now() - timedelta(seconds=1))

    first_purge = purge_expired_public_comparisons()
    second_purge = purge_expired_public_comparisons()

    assert first_purge == 201
    assert second_purge == 0
