"""Observable report contract and bounded database work."""

import logging
import tracemalloc
from datetime import datetime, timedelta

import pytest
from checks.models import CheckResult, CheckRun
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from documents.models import Document, DocumentVersion
from observations.models import Observation
from reviews.models import Seal, SealValidityRecord

LOGGER = logging.getLogger(__name__)


def _run(version, config, created_at, status=CheckRun.Status.DONE):
    run = CheckRun.objects.create(document_version=version, config_version=config, status=status)
    CheckRun.objects.filter(pk=run.pk).update(created_at=created_at)
    return run


def _report_query_count(client, url):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url)
    if response.status_code != 200:
        raise AssertionError(response.data)
    return len(queries), response


def _create_report_documents(make_document, count, start=0):
    """Build populated three-version histories without new users or uploads."""
    records = []
    evidence = {'proof': 'x' * (128 * 1024)}
    for number in range(start, start + count):
        document, versions = make_document(n_versions=3, document_slug=f'fila-{number}')
        Observation.objects.create(
            document=document, created_on_version=versions[2], author=versions[2].author,
            body='abierta',
        )
        run = CheckRun.objects.create(
            document_version=versions[2], config_version=versions[2].config_version,
        )
        CheckResult.objects.create(
            check_run=run, key='pass', label='Pass', outcome=CheckResult.Outcome.PASS,
        )
        seal = Seal.objects.create(
            document_version=versions[0], reviewer=versions[0].author,
            signed_payload={}, signature=f'signature-{number}', key_id=f'key-{number}',
        )
        records.extend([
            SealValidityRecord(
                seal=seal, to_document_version=versions[1],
                decision=SealValidityRecord.Decision.PRESERVED, evidence=evidence,
            ),
            SealValidityRecord(
                seal=seal, to_document_version=versions[2],
                decision=SealValidityRecord.Decision.PRESERVED, evidence=evidence,
            ),
        ])
    SealValidityRecord.objects.bulk_create(records, batch_size=20)


def _assert_populated_report_row(row):
    assert (
        row['checks'], row['open_observations'], row['valid_seals'],
    ) == (
        {'pass': 1, 'warn': 0, 'fail': 0}, 1, 1,
    )


@pytest.fixture
def report_contract_data(document_with_versions, versiona_context):
    """Create report rows that distinguish alive versions and check-run states."""
    report_document, report_versions = document_with_versions(
        n_versions=2, document_slug='reportado',
    )
    no_run_document, _ = document_with_versions(n_versions=1, document_slug='sin-corrida')
    empty_document, empty_versions = document_with_versions(n_versions=1, document_slug='vacia')
    Document.objects.create(project=versiona_context.project, title='Sin versión', slug='sin-version')
    DocumentVersion.all_objects.filter(pk=report_versions[1].pk).update(
        deleted_at=timezone.make_aware(datetime(2026, 10, 2, 11, 0, 0)),
    )
    Observation.objects.create(
        document=report_document, created_on_version=report_versions[0],
        author=versiona_context.users['reviewer'], body='abierta',
    )
    base = timezone.make_aware(datetime(2026, 10, 2, 12, 0, 0))
    completed = _run(report_versions[0], versiona_context.config, base)
    CheckResult.objects.create(check_run=completed, key='pass', label='Pass', outcome='pass')
    CheckResult.objects.create(check_run=completed, key='warn', label='Warn', outcome='warn')
    CheckResult.objects.create(check_run=completed, key='fail', label='Fail', outcome='fail')
    _run(report_versions[0], versiona_context.config, base + timedelta(seconds=1), CheckRun.Status.FAILED)
    _run(empty_versions[0], versiona_context.config, base)

    return {
        'url': f'/api/projects/{versiona_context.project.public_id}/report/',
        'report_document': report_document,
        'no_run_document': no_run_document,
        'empty_document': empty_document,
    }


def _report_rows(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return {row['document']: row for row in response.data['documents']}


@pytest.mark.django_db
def test_project_report_keeps_its_public_envelope(client_as, report_contract_data):
    """Catches: a projection rewrite changing the report's top-level API contract."""
    response = client_as('viewer').get(report_contract_data['url'])

    assert set(response.data) == {'project', 'status', 'generated_at', 'documents'}


@pytest.mark.django_db
def test_project_report_omits_document_without_alive_version(client_as, report_contract_data):
    """Catches: a report displaying a document whose only version is trashed."""
    rows = _report_rows(client_as('viewer'), report_contract_data['url'])

    assert 'Sin versión' not in rows


@pytest.mark.django_db
def test_project_report_uses_latest_alive_version(client_as, report_contract_data):
    """Catches: a trashed later version replacing the latest live report version."""
    rows = _report_rows(client_as('viewer'), report_contract_data['url'])

    assert rows[report_contract_data['report_document'].title]['latest_version'] == 1


@pytest.mark.django_db
def test_project_report_uses_none_without_completed_check(client_as, report_contract_data):
    """Catches: a report inventing check counters when no completed run exists."""
    rows = _report_rows(client_as('viewer'), report_contract_data['url'])

    assert rows[report_contract_data['no_run_document'].title]['checks'] is None


@pytest.mark.django_db
def test_project_report_uses_zero_counts_for_empty_completed_check(client_as, report_contract_data):
    """Catches: an empty completed run being confused with absent check data."""
    rows = _report_rows(client_as('viewer'), report_contract_data['url'])

    assert rows[report_contract_data['empty_document'].title]['checks'] == {
        'pass': 0, 'warn': 0, 'fail': 0,
    }


@pytest.mark.django_db
def test_project_report_uses_latest_completed_check_counts(client_as, report_contract_data):
    """Catches: a later failed run replacing counters from the latest completed run."""
    rows = _report_rows(client_as('viewer'), report_contract_data['url'])

    assert rows[report_contract_data['report_document'].title]['checks'] == {
        'pass': 1, 'warn': 1, 'fail': 1,
    }


@pytest.mark.django_db
def test_project_report_query_count_does_not_grow_with_document_history(
    client_as, document_with_versions, versiona_context,
):
    """Catches: report output loading historical evidence once per document."""
    _create_report_documents(document_with_versions, 1)
    url = f'/api/projects/{versiona_context.project.public_id}/report/'
    client = client_as('viewer')
    first_count, first_response = _report_query_count(client, url)
    _create_report_documents(document_with_versions, 99, start=1)

    tracemalloc.start()
    try:
        many_count, many_response = _report_query_count(client, url)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(first_response.data['documents']) == 1
    assert len(many_response.data['documents']) == 100
    _assert_populated_report_row(many_response.data['documents'][0])
    assert many_count == first_count
    assert many_count <= 6
    assert peak < 25 * 1024 * 1024
    LOGGER.info(
        'report query budget: one=%s hundred=%s peak_bytes=%s', first_count, many_count, peak,
    )
