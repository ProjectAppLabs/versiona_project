"""Query budgets for the viewer's seal, seal-plan and review-request panels.

Every version page loads these three panels, so their reads must not grow
with the seals, inherited validity records or review requests they list.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from documents.models import Section

from reviews.models import (
    ReviewAssignment,
    ReviewRequest,
    Seal,
    SealSection,
    SealValidityRecord,
)
from reviews.serializers import SealSerializer, SealValidityRecordSerializer

# Shared authorization reads the version and both memberships (3 queries);
# the remaining reads are the panel's own lists and their prefetched relations.
MAX_SEAL_PANEL_QUERIES = 9
MAX_SEAL_PLAN_QUERIES = 6
MAX_REVIEW_PANEL_QUERIES = 6


def _user(django_user_model, tag, index):
    return django_user_model.objects.create_user(email=f'{tag}-{index}@versiona.test')


def _versions_with_sections(document_with_versions, slug, section_count):
    document, versions = document_with_versions(2, document_slug=slug)
    sections = [
        Section.objects.create(
            document=document, stable_key=f'clausula-{index}',
            title_current=f'Cláusula {index}', created_in_version=versions[0],
        )
        for index in range(section_count)
    ]
    return versions, sections


def _coverage(sections, index):
    # A distinct subset per seal, inserted in reverse so sorting is observable;
    # no sections means a whole-document seal.
    start = index % len(sections) if sections else 0
    return sections[start:][::-1]


def _seal(version, reviewer, sections):
    seal = Seal.objects.create(
        document_version=version, reviewer=reviewer, covers_all=not sections,
        signed_payload={}, signature=f'firma-{version.pk}-{reviewer.pk}', key_id='budget-key',
    )
    SealSection.objects.bulk_create([
        SealSection(seal=seal, section=section, body_hash=f'{position:064d}')
        for position, section in enumerate(sections)
    ])
    return seal


def _sealed_panel(document_with_versions, django_user_model, slug, count, section_count):
    """Version 2 with `count` own seals plus `count` seals preserved from version 1."""
    (first, second), sections = _versions_with_sections(
        document_with_versions, slug, section_count
    )
    for index in range(count):
        _seal(second, _user(django_user_model, f'{slug}-own', index), _coverage(sections, index))
        inherited = _seal(
            first, _user(django_user_model, f'{slug}-inherited', index), _coverage(sections, index)
        )
        SealValidityRecord.objects.create(
            seal=inherited, to_document_version=second,
            decision=SealValidityRecord.Decision.PRESERVED, reason_code='unchanged',
        )
    return second


def _pending_plan(document_with_versions, django_user_model, slug, count, section_count):
    """Version 2 with `count` coordinator records awaiting confirmation."""
    (first, second), sections = _versions_with_sections(
        document_with_versions, slug, section_count
    )
    for index in range(count):
        seal = _seal(
            first, _user(django_user_model, f'{slug}-reviewer', index), _coverage(sections, index)
        )
        SealValidityRecord.objects.create(
            seal=seal, to_document_version=second,
            decision=SealValidityRecord.Decision.PENDING,
            proposed_decision=SealValidityRecord.Decision.PRESERVED,
            decided_mode=SealValidityRecord.Mode.COORDINATOR,
        )
    return second


def _requested_version(document_with_versions, django_user_model, slug, count):
    """One open request plus cancelled ones, each from and to distinct users."""
    _, (version,) = document_with_versions(1, document_slug=slug)
    statuses = [ReviewRequest.Status.OPEN] + [ReviewRequest.Status.CANCELLED] * (count - 1)
    for index, request_status in enumerate(statuses):
        review = ReviewRequest.objects.create(
            document_version=version, status=request_status,
            requested_by=_user(django_user_model, f'{slug}-requester', index),
        )
        ReviewAssignment.objects.create(
            review_request=review, reviewer=_user(django_user_model, f'{slug}-reviewer', index),
        )
    return version


def _seal_id(record):
    return record['seal']['public_id']


@pytest.mark.django_db
@pytest.mark.parametrize('section_count', [3, 0], ids=['section-seals', 'whole-document-seals'])
def test_seal_panel_queries_stay_constant_for_10_seals(
    client_as, document_with_versions, django_user_model, section_count,
    record_testsuite_property,
):
    """Own seals with inherited validity records must not add reads per listed row."""
    one = _sealed_panel(
        document_with_versions, django_user_model, f'panel-one-{section_count}', 1, section_count
    )
    ten = _sealed_panel(
        document_with_versions, django_user_model, f'panel-ten-{section_count}', 10, section_count
    )
    client = client_as('viewer')

    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(f'/api/versions/{one.public_id}/seals/')
    with CaptureQueriesContext(connection) as ten_queries:
        ten_response = client.get(f'/api/versions/{ten.public_id}/seals/')

    assert one_response.status_code == 200
    assert len(ten_response.data['seals']) == 10
    assert len(ten_response.data['validity_records']) == 10
    assert len(one_queries) == len(ten_queries)
    assert len(ten_queries) <= MAX_SEAL_PANEL_QUERIES
    record_testsuite_property(f'seal_panel_queries_1_{section_count}', len(one_queries))
    record_testsuite_property(f'seal_panel_queries_10_{section_count}', len(ten_queries))


@pytest.mark.django_db
@pytest.mark.parametrize('section_count', [3, 0], ids=['section-seals', 'whole-document-seals'])
def test_seal_plan_queries_stay_constant_for_10_pending_records(
    client_as, document_with_versions, django_user_model, section_count,
    record_testsuite_property,
):
    """Pending D5 records must not read their target version or coverage per row."""
    one = _pending_plan(
        document_with_versions, django_user_model, f'plan-one-{section_count}', 1, section_count
    )
    ten = _pending_plan(
        document_with_versions, django_user_model, f'plan-ten-{section_count}', 10, section_count
    )
    client = client_as('viewer')

    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(f'/api/versions/{one.public_id}/seal_plan/')
    with CaptureQueriesContext(connection) as ten_queries:
        ten_response = client.get(f'/api/versions/{ten.public_id}/seal_plan/')

    assert one_response.status_code == 200
    assert len(ten_response.data['pending']) == 10
    assert len(one_queries) == len(ten_queries)
    assert len(ten_queries) <= MAX_SEAL_PLAN_QUERIES
    record_testsuite_property(f'seal_plan_queries_1_{section_count}', len(one_queries))
    record_testsuite_property(f'seal_plan_queries_10_{section_count}', len(ten_queries))


@pytest.mark.django_db
def test_review_panel_queries_stay_constant_for_10_requests(
    client_as, document_with_versions, django_user_model, record_testsuite_property
):
    """Requesters, version numbers and assigned reviewers must not load per request."""
    one = _requested_version(document_with_versions, django_user_model, 'reviews-one', 1)
    ten = _requested_version(document_with_versions, django_user_model, 'reviews-ten', 10)
    client = client_as('viewer')

    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(f'/api/versions/{one.public_id}/reviews/')
    with CaptureQueriesContext(connection) as ten_queries:
        ten_response = client.get(f'/api/versions/{ten.public_id}/reviews/')

    assert one_response.status_code == 200
    assert len(ten_response.data['results']) == 10
    assert len(one_queries) == len(ten_queries)
    assert len(ten_queries) <= MAX_REVIEW_PANEL_QUERIES
    record_testsuite_property('review_panel_queries_1', len(one_queries))
    record_testsuite_property('review_panel_queries_10', len(ten_queries))


@pytest.mark.django_db
def test_seal_panel_payload_matches_unprefetched_serializers(
    client_as, document_with_versions, django_user_model
):
    """Prefetched coverage must serialize the same sorted keys as a direct read."""
    version = _sealed_panel(document_with_versions, django_user_model, 'panel-payload', 3, 3)
    expected_seals = SealSerializer(Seal.objects.filter(document_version=version), many=True).data
    expected_records = SealValidityRecordSerializer(
        SealValidityRecord.objects.filter(to_document_version=version), many=True
    ).data

    response = client_as('viewer').get(f'/api/versions/{version.public_id}/seals/')

    assert response.status_code == 200
    assert response.data['seals'] == expected_seals
    assert sorted(response.data['validity_records'], key=_seal_id) == sorted(
        expected_records, key=_seal_id
    )
