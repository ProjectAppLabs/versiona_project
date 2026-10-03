"""D3 endpoint guards for replies and the I14 state machine.

Anchored flows live in test_observations.py and use engine fixtures.
"""

import tracemalloc
from datetime import datetime
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from observations.models import Observation, ObservationAnchor, ObservationReply

FIXED_TIME = timezone.make_aware(datetime(2026, 10, 2, 12, 0, 0))


@pytest.fixture
def doc_version(document_with_versions):
    """Provide one document and its first ready version."""
    document, versions = document_with_versions(n_versions=1)
    return document, versions[0]


@pytest.fixture
def open_observation(doc_version, versiona_context):
    """Provide one open thread visible to project members."""
    document, version = doc_version
    return Observation.objects.create(
        document=document,
        created_on_version=version,
        author=versiona_context.users['reviewer'],
        body='La multa del 2% parece baja.',
    )


def _ordered_public_ids(document):
    """Return the contractual newest-first thread order."""
    return [
        str(public_id) for public_id in Observation.objects.filter(document=document)
        .order_by('-pk').values_list('public_id', flat=True)
    ]


def _cursor_response(client, version, cursor, cursor_kind):
    """Issue the selected invalid cursor request."""
    if cursor_kind == 'other_filter':
        return client.get(
            f'/api/versions/{version.public_id}/observations/',
            {'status': 'resolved', 'cursor': cursor},
        )
    return client.get(
        f'/api/versions/{version.public_id}/observations/', {'cursor': f'{cursor}x'},
    )


def _request_query_count(client, url):
    """Return one successful GET and its database query count."""
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url)
    assert response.status_code == 200
    return len(queries), response


def _thread_with_reply_page(document, version, user):
    """Create more replies than one fixed-size page."""
    observation = Observation.objects.create(
        document=document, created_on_version=version, author=user, body='paginable',
    )
    replies = [
        ObservationReply(observation=observation, author=user, body=f'respuesta {number}')
        for number in range(26)
    ]
    ObservationReply.objects.bulk_create(replies)
    ObservationReply.objects.filter(observation=observation).update(created_at=FIXED_TIME)
    return observation


def _thread_with_anchor_page(document, versions, user):
    """Create one retained anchor for every supplied document version."""
    observation = Observation.objects.create(
        document=document, created_on_version=versions[0], author=user, body='historial',
    )
    ObservationAnchor.objects.bulk_create([
        ObservationAnchor(
            observation=observation, document_version=version, quads=[{'page': 1}],
            method=ObservationAnchor.Method.EXACT,
        ) for version in versions
    ])
    return observation


def _create_open_threads(document, version, user, count):
    """Create enough same-filter threads to obtain a continuation cursor."""
    for number in range(count):
        Observation.objects.create(
            document=document, created_on_version=version, author=user, body=f'hilo {number}',
        )


@pytest.mark.django_db
@pytest.mark.escenario('D3-A02')
def test_observations_list_filters_by_status(client_as, doc_version, versiona_context, open_observation):
    """Resolved filtering returns only the resolved thread."""
    document, version = doc_version
    resolved = Observation.objects.create(
        document=document,
        created_on_version=version,
        author=versiona_context.users['reviewer'],
        body='Ya resuelta.',
        status=Observation.Status.RESOLVED,
    )

    response = client_as('viewer').get(
        f'/api/versions/{version.public_id}/observations/', {'status': 'resolved'}
    )

    assert response.status_code == 200
    assert len(response.data['results']) == 1
    assert response.data['results'][0]['public_id'] == str(resolved.public_id)


@pytest.mark.django_db
@pytest.mark.escenario('D3-E01')
def test_create_observation_on_unknown_section_returns_error(client_as, doc_version):
    """Creating against an unknown section returns the API validation error."""
    _, version = doc_version

    response = client_as('reviewer').post(
        f'/api/versions/{version.public_id}/observations/',
        {'body': 'obs', 'section_key': 'no-existe'},
        format='json',
    )

    assert response.status_code == 400
    assert response.data['error'] == 'La sección "no-existe" no existe en esta versión.'


@pytest.mark.django_db
@pytest.mark.escenario('D3-F02')
def test_editor_reply_marks_thread_answered(client_as, open_observation):
    """An editor reply creates one reply and advances the thread status."""
    response = client_as('editor').post(
        f'/api/observations/{open_observation.public_id}/replies/',
        {'body': 'Lo subimos al 5%.'},
        format='json',
    )

    assert response.status_code == 201
    assert response.data['status'] == 'answered'
    assert ObservationReply.objects.filter(observation=open_observation).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('D3-P02')
def test_viewer_cannot_reply_to_observation(client_as, open_observation):
    """Viewer cannot mutate an otherwise visible thread."""
    response = client_as('viewer').post(
        f'/api/observations/{open_observation.public_id}/replies/',
        {'body': 'intento'},
        format='json',
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.escenario('D3-P04')
def test_reply_to_unknown_observation_returns_404(client_as, versiona_context):
    """Replying to an unknown public ID remains hidden."""
    response = client_as('editor').post(
        f'/api/observations/{uuid4()}/replies/', {'body': 'hola'}, format='json'
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.escenario('D3-P04')
def test_reply_from_non_member_returns_404(client_as, open_observation):
    """A foreign-tenant member cannot reply to the thread."""
    response = client_as('non_member').post(
        f'/api/observations/{open_observation.public_id}/replies/',
        {'body': 'ajeno'},
        format='json',
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.escenario('D3-E01')
def test_reply_without_body_returns_validation_error(client_as, open_observation):
    """An empty reply reports the concrete body validation error."""
    response = client_as('editor').post(
        f'/api/observations/{open_observation.public_id}/replies/', {}, format='json'
    )

    assert response.status_code == 400
    assert response.data['error'] == 'La respuesta necesita un texto.'


@pytest.mark.django_db
@pytest.mark.escenario('D3-F02')
def test_author_resolves_answered_thread_via_api(client_as, doc_version, versiona_context):
    """The author can resolve an answered thread through its public route."""
    document, version = doc_version
    observation = Observation.objects.create(
        document=document,
        created_on_version=version,
        author=versiona_context.users['reviewer'],
        body='Pendiente de cierre.',
        status=Observation.Status.ANSWERED,
    )

    response = client_as('reviewer').post(
        f'/api/observations/{observation.public_id}/status/',
        {'status': 'resolved'},
        format='json',
    )

    assert response.status_code == 200
    assert response.data['status'] == 'resolved'
    assert response.data['resolved_in'] == 1


@pytest.mark.django_db
@pytest.mark.escenario('D3-P02')
def test_viewer_cannot_change_observation_status(client_as, open_observation):
    """Viewer cannot alter thread state."""
    response = client_as('viewer').post(
        f'/api/observations/{open_observation.public_id}/status/',
        {'status': 'answered'},
        format='json',
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.escenario('D3-E01')
def test_invalid_status_transition_returns_conflict(client_as, open_observation):
    """I14 rejects a direct open-to-resolved transition."""
    response = client_as('reviewer').post(
        f'/api/observations/{open_observation.public_id}/status/',
        {'status': 'resolved'},
        format='json',
    )

    assert response.status_code == 409
    assert 'I14' in response.data['error']


@pytest.mark.django_db
def test_observation_pages_use_primary_key_to_break_equal_timestamps(
    client_as, doc_version, versiona_context,
):
    """Catches: a cursor that loses or duplicates threads sharing a timestamp."""
    document, version = doc_version
    observations = [
        Observation.objects.create(
            document=document, created_on_version=version,
            author=versiona_context.users['reviewer'], body=f'hilo {number}',
        )
        for number in range(26)
    ]
    Observation.objects.filter(pk__in=[item.pk for item in observations]).update(created_at=FIXED_TIME)
    client = client_as('viewer')

    first = client.get(f'/api/versions/{version.public_id}/observations/')
    second = client.get(
        f'/api/versions/{version.public_id}/observations/',
        {'cursor': first.data['next_cursor']},
    )

    returned = [row['public_id'] for row in first.data['results'] + second.data['results']]
    expected = _ordered_public_ids(document)
    assert len(first.data['results']) == 25
    assert len(second.data['results']) == 1
    assert returned == expected


@pytest.mark.django_db
@pytest.mark.parametrize('cursor_kind', ['other_filter', 'tampered'])
def test_observation_page_rejects_cursor_outside_its_filter(
    client_as, doc_version, versiona_context, cursor_kind,
):
    """Catches: a signed page cursor leaking rows across a status query."""
    document, version = doc_version
    _create_open_threads(document, version, versiona_context.users['reviewer'], 26)
    client = client_as('viewer')
    active = client.get(f'/api/versions/{version.public_id}/observations/', {'status': 'active'})
    cursor = active.data['next_cursor']
    response = _cursor_response(client, version, cursor, cursor_kind)

    assert response.status_code == 400
    assert 'cursor' in response.data


@pytest.mark.django_db
@pytest.mark.parametrize('endpoint', ['detail', 'replies', 'anchors', 'body', 'reply_body', 'anchor_body'])
def test_progressive_read_endpoints_hide_other_tenant_threads(
    client_as, open_observation, doc_version, versiona_context, endpoint,
):
    """Catches: a progressive GET bypassing the tenant-aware observation loader."""
    _, version = doc_version
    reply = ObservationReply.objects.create(
        observation=open_observation, author=versiona_context.users['editor'], body='respuesta',
    )
    ObservationAnchor.objects.create(
        observation=open_observation, document_version=version, quads=[{'page': 1}],
        method=ObservationAnchor.Method.EXACT,
    )
    base = f'/api/observations/{open_observation.public_id}'
    urls = {
        'detail': f'{base}/', 'replies': f'{base}/replies/', 'anchors': f'{base}/anchors/',
        'body': f'{base}/content/',
        'reply_body': f'{base}/replies/{reply.public_id}/content/',
        'anchor_body': f'{base}/anchors/{version.number}/content/',
    }

    response = client_as('non_member').get(urls[endpoint])

    assert response.status_code == 404


@pytest.mark.django_db
def test_observation_reply_response_omits_historical_collections(client_as, open_observation):
    """Catches: replying materializing the thread's complete reply or anchor history."""
    response = client_as('editor').post(
        f'/api/observations/{open_observation.public_id}/replies/', {'body': 'respuesta'}, format='json',
    )

    assert response.status_code == 201
    assert set(response.data) == {'reply', 'status'}
    assert set(response.data['reply']) >= {'public_id', 'body_preview', 'body_content_url'}


@pytest.mark.django_db
def test_observation_status_response_omits_historical_collections(client_as, doc_version, versiona_context):
    """Catches: changing status serializing anchors or replies instead of one thread summary."""
    document, version = doc_version
    observation = Observation.objects.create(
        document=document, created_on_version=version, author=versiona_context.users['reviewer'],
        body='respondida', status=Observation.Status.ANSWERED,
    )

    response = client_as('reviewer').post(
        f'/api/observations/{observation.public_id}/status/', {'status': 'resolved'}, format='json',
    )

    assert response.status_code == 200
    assert response.data['status'] == 'resolved'
    assert 'anchors' not in response.data
    assert 'replies' not in response.data


@pytest.mark.django_db
def test_trashed_anchor_history_keeps_quads_content_route(client_as, open_observation, doc_version):
    """Catches: trashing a historical version erasing observation anchor evidence."""
    _, version = doc_version
    ObservationAnchor.objects.create(
        observation=open_observation, document_version=version, quads=[{'page': 1, 'x0': 0}],
        method=ObservationAnchor.Method.EXACT,
    )
    from documents.models import DocumentVersion
    DocumentVersion.all_objects.filter(pk=version.pk).update(deleted_at=FIXED_TIME)

    history = client_as('viewer').get(f'/api/observations/{open_observation.public_id}/anchors/')
    content = client_as('viewer').get(
        f'/api/observations/{open_observation.public_id}/anchors/{version.number}/content/'
    )

    assert history.status_code == 200
    assert history.data['results'][0]['version_is_trashed'] is True
    assert history.data['results'][0]['quads_content_url'].endswith('/content/')
    assert content.status_code == 200


@pytest.mark.django_db
def test_reply_pages_keep_equal_timestamp_rows_without_duplication(
    client_as, document_with_versions, versiona_context,
):
    """Catches: reply keyset pagination omitting a same-time reply at page boundary."""
    document, versions = document_with_versions(n_versions=1, document_slug='respuestas-pagina')
    observation = _thread_with_reply_page(document, versions[0], versiona_context.users['reviewer'])
    client = client_as('viewer')
    first = client.get(f'/api/observations/{observation.public_id}/replies/')
    second = client.get(
        f'/api/observations/{observation.public_id}/replies/', {'cursor': first.data['next_cursor']},
    )

    returned = [row['public_id'] for row in first.data['results'] + second.data['results']]
    expected = [
        str(public_id) for public_id in ObservationReply.objects.filter(observation=observation)
        .order_by('-created_at', '-pk').values_list('public_id', flat=True)
    ]
    assert returned == expected


@pytest.mark.django_db
def test_anchor_history_pages_keep_every_version(client_as, document_with_versions, versiona_context):
    """Catches: history pagination dropping the twenty-sixth retained anchor."""
    document, versions = document_with_versions(n_versions=26, document_slug='anclas-pagina')
    observation = _thread_with_anchor_page(document, versions, versiona_context.users['reviewer'])
    client = client_as('viewer')
    first = client.get(f'/api/observations/{observation.public_id}/anchors/')
    second = client.get(
        f'/api/observations/{observation.public_id}/anchors/', {'cursor': first.data['next_cursor']},
    )

    returned = [row['version_number'] for row in first.data['results'] + second.data['results']]
    assert returned == list(range(26, 0, -1))


@pytest.mark.django_db
def test_observation_detail_uses_bounded_query_count(client_as, open_observation):
    """Catches: one detail summary loading the complete reply or anchor collections."""
    count, response = _request_query_count(
        client_as('viewer'), f'/api/observations/{open_observation.public_id}/',
    )

    assert response.data['body_preview'] == open_observation.body
    assert count <= 4


@pytest.mark.django_db
def test_observation_content_uses_bounded_query_count(client_as, open_observation):
    """Catches: one content chunk issuing extra queries for historical children."""
    count, response = _request_query_count(
        client_as('viewer'), f'/api/observations/{open_observation.public_id}/content/',
    )

    assert response.data['content'] == open_observation.body
    assert count <= 4


@pytest.mark.django_db
def test_observation_page_keeps_large_history_out_of_memory(client_as, open_observation, doc_version):
    """Catches: listing threads materializing a retained long body or all anchor history."""
    _, version = doc_version
    long_body = 'ñ😀' * 140_000
    Observation.objects.filter(pk=open_observation.pk).update(body=long_body)
    ObservationAnchor.objects.create(
        observation=open_observation, document_version=version, quads=[{'page': 1}],
        method=ObservationAnchor.Method.EXACT,
    )
    tracemalloc.start()
    try:
        count, response = _request_query_count(
            client_as('viewer'), f'/api/versions/{version.public_id}/observations/',
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count <= 6
    assert peak < 25 * 1024 * 1024
    assert len(response.content) < 256 * 1024
    assert response.data['results'][0]['body_preview'] == long_body[:500]
    assert response.data['results'][0]['current_anchor']['version_number'] == 1


@pytest.mark.django_db
@pytest.mark.parametrize('suffix', ['replies/', 'anchors/'])
def test_observation_child_page_uses_bounded_query_count(
    client_as, open_observation, doc_version, versiona_context, suffix,
):
    """Catches: a child page loading every retained reply or anchor before paging."""
    _, version = doc_version
    ObservationReply.objects.create(
        observation=open_observation, author=versiona_context.users['editor'], body='respuesta',
    )
    ObservationAnchor.objects.create(
        observation=open_observation, document_version=version, quads=[{'page': 1}],
        method=ObservationAnchor.Method.EXACT,
    )
    count, response = _request_query_count(
        client_as('viewer'), f'/api/observations/{open_observation.public_id}/{suffix}',
    )

    assert len(response.data['results']) == 1
    assert count <= 6
