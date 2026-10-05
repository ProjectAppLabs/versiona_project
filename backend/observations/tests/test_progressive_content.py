"""D3 progressive text endpoints retain Unicode and tenant isolation."""

import json

import pytest

from observations.models import Observation, ObservationAnchor, ObservationReply


def _read_chunks(client, url):
    """Follow server-issued character offsets without assuming byte lengths."""
    offset = 0
    pieces = []
    while True:
        response = client.get(url, {'offset': str(offset)})
        assert response.status_code == 200
        assert len(response.content) < 256 * 1024
        assert len(response.data['content']) <= 8192
        pieces.append(response.data['content'])
        if response.data['eof']:
            assert response.data['next_offset'] is None
            return ''.join(pieces)
        offset = response.data['next_offset']


@pytest.fixture
def progressive_thread(document_with_versions, versiona_context):
    """Create one thread with long body, reply and retained anchor JSON."""
    document, versions = document_with_versions(n_versions=1, document_slug='progresivo')
    observation = Observation.objects.create(
        document=document, created_on_version=versions[0],
        author=versiona_context.users['reviewer'], body='ñ😀' * 140_000,
    )
    reply = ObservationReply.objects.create(
        observation=observation, author=versiona_context.users['editor'], body='á界' * 10_000,
    )
    quads = [{'page': 1, 'note': '坐標😀' * 100_000}]
    ObservationAnchor.objects.create(
        observation=observation, document_version=versions[0], page=1, quads=quads,
        text_snippet='ancla', method=ObservationAnchor.Method.EXACT,
    )
    return observation, reply, quads


@pytest.mark.django_db
def test_observation_content_reconstructs_unicode_by_character_offset(client_as, progressive_thread):
    """Catches: body chunks cut multibyte text or advance offsets as UTF-8 bytes."""
    observation, _, _ = progressive_thread

    content = _read_chunks(client_as('viewer'), f'/api/observations/{observation.public_id}/content/')

    assert content == observation.body


@pytest.mark.django_db
def test_reply_content_is_scoped_to_its_observation(client_as, progressive_thread):
    """Catches: reply content being selected by global UUID without thread ownership."""
    observation, reply, _ = progressive_thread

    content = _read_chunks(
        client_as('viewer'),
        f'/api/observations/{observation.public_id}/replies/{reply.public_id}/content/',
    )

    assert content == reply.body


@pytest.mark.django_db
def test_reply_content_rejects_a_reply_owned_by_another_thread(
    client_as, progressive_thread,
):
    """Catches: a global reply UUID exposing text through a different thread route."""
    observation, reply, _ = progressive_thread
    other = Observation.objects.create(
        document=observation.document, created_on_version=observation.created_on_version,
        author=observation.author, body='otro hilo',
    )

    response = client_as('viewer').get(
        f'/api/observations/{other.public_id}/replies/{reply.public_id}/content/'
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_anchor_quads_reconstruct_as_the_stored_json_value(client_as, progressive_thread):
    """Catches: anchor content returning only one fragment or a different thread's JSON."""
    observation, _, quads = progressive_thread

    content = _read_chunks(
        client_as('viewer'),
        f'/api/observations/{observation.public_id}/anchors/1/content/',
    )

    assert len(json.dumps(quads, ensure_ascii=False).encode()) > 256 * 1024
    assert json.loads(content) == quads


@pytest.mark.django_db
@pytest.mark.parametrize('offset', ['-1', '1.5', str(2 ** 32), '999999999'])
def test_content_rejects_invalid_http_offset(client_as, progressive_thread, offset):
    """Catches: negative or oversized offsets reaching an ambiguous SQL slice."""
    observation, _, _ = progressive_thread

    response = client_as('viewer').get(
        f'/api/observations/{observation.public_id}/content/', {'offset': offset},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_observation_summary_keeps_a_large_body_out_of_the_page_response(
    client_as, progressive_thread,
):
    """Catches: the thread list materializing a legacy long body instead of its preview."""
    observation, _, _ = progressive_thread

    response = client_as('viewer').get(
        f'/api/versions/{observation.created_on_version.public_id}/observations/'
    )

    assert response.status_code == 200
    assert len(response.content) < 256 * 1024
    assert response.data['results'][0]['body_preview'] == observation.body[:500]
    assert response.data['results'][0]['body_content_url'].endswith('/content/')
