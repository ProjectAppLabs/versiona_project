"""Version detail loads section identities without a query for each snapshot."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from documents.models import Section, SectionVersion
from documents.serializers import VersionDetailSerializer


def _add_sections(document, version, count):
    for index in range(count):
        section = Section.objects.create(
            document=document, stable_key=f'section-{index}', title_current=f'Sección {index}',
            level=index % 2 + 1, created_in_version=version,
        )
        SectionVersion.objects.create(
            section=section, document_version=version, heading_text=section.title_current,
            heading_hash=f'{index:064d}', body_hash=f'{index + 1:064d}', normalized_text='Texto',
            order_index=count - index - 1, page_start=index + 1, page_end=index + 1,
            char_count=5, bboxes=[{'page': index + 1, 'x0': 0.1, 'y0': 0.2, 'x1': 0.3, 'y1': 0.4}],
        )


@pytest.mark.django_db
@pytest.mark.parametrize('role', ['owner', 'reviewer'])
def test_version_detail_queries_stay_constant_for_50_sections(
    client_as, document_with_versions, role, record_testsuite_property
):
    """Reading stable keys and levels must not add a section query for every snapshot."""
    one_document, one_versions = document_with_versions(1, document_slug='detail-one-section')
    many_document, many_versions = document_with_versions(1, document_slug='detail-many-sections')
    _add_sections(one_document, one_versions[0], 1)
    _add_sections(many_document, many_versions[0], 50)
    client = client_as(role)

    with CaptureQueriesContext(connection) as one_queries:
        one_response = client.get(f'/api/versions/{one_versions[0].public_id}/')
    with CaptureQueriesContext(connection) as many_queries:
        many_response = client.get(f'/api/versions/{many_versions[0].public_id}/')

    assert one_response.status_code == 200
    assert many_response.status_code == 200
    assert len(one_queries) == len(many_queries)
    assert len(many_response.data['sections']) == 50
    record_testsuite_property(f'version_detail_queries_1_section_{role}', len(one_queries))
    record_testsuite_property(f'version_detail_queries_50_sections_{role}', len(many_queries))


@pytest.mark.django_db
def test_version_detail_preserves_section_payload_order(client_as, document_with_versions):
    """A prepared detail must retain section identities, levels, coordinates and snapshot order."""
    document, versions = document_with_versions(1, document_slug='detail-section-order')
    _add_sections(document, versions[0], 3)
    expected = VersionDetailSerializer(versions[0]).data['sections']

    response = client_as('viewer').get(f'/api/versions/{versions[0].public_id}/')

    assert response.status_code == 200
    assert response.data['sections'] == expected
    assert [section['stable_key'] for section in response.data['sections']] == [
        'section-2', 'section-1', 'section-0'
    ]


@pytest.mark.django_db
def test_version_detail_preserves_empty_sections(client_as, document_with_versions):
    """A version without section snapshots must still return an empty collection."""
    _, versions = document_with_versions(1, document_slug='detail-empty')

    response = client_as('viewer').get(f'/api/versions/{versions[0].public_id}/')

    assert response.status_code == 200
    assert response.data['sections'] == []
