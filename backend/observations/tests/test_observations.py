"""D3: anchored threads, the I14 state machine and re-anchoring.

Verified against the truth table (contrato v1→v2: §3 changes ⇒ reanchored ·
§6 removed ⇒ orphaned · §1 intact ⇒ exact).
"""

from pathlib import Path

import pytest
from documents.models import SectionVersion
from documents.services import storage_service, version_service
from notifications.models import Notification

from observations import services
from observations.models import Observation, ObservationAnchor

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


def upload(document, fixture, message, author):
    """Upload a fixture PDF as a new version and return it."""
    intent = version_service.create_upload_intent(document, author)
    storage_service.put_bytes(intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf')
    version, _ = version_service.complete_upload(document, intent.upload_id, message, author)
    return version


@pytest.fixture
def with_v1(versiona_context):
    """Build a document with an uploaded v1 (contrato_v1.pdf) for observation tests."""
    editor = versiona_context.users['editor']
    document = version_service.create_document(versiona_context.project, 'Observado', editor)
    return versiona_context, document, upload(document, 'contrato_v1.pdf', 'v1', editor)


@pytest.mark.django_db
@pytest.mark.escenario('D3-F01')
def test_observation_anchors_to_a_section_with_its_bboxes(with_v1):
    """Catches create_observation copying the wrong section's bboxes.

    Also catches an empty-but-truthy placeholder — a bare truthy check cannot
    tell those apart from the real section coordinates it is supposed to
    inherit.
    """
    context, document, v1 = with_v1

    observation = services.create_observation(
        v1, context.users['reviewer'],
        body='La multa del 2% parece baja para este contrato.',
        section_key='obligaciones-del-contratista',
    )

    anchor = observation.anchors.get()
    section_bboxes = SectionVersion.objects.get(
        document_version=v1, section__stable_key='obligaciones-del-contratista'
    ).bboxes
    assert section_bboxes != []  # guard: the equality below must not pass vacuously on []
    assert anchor.method == ObservationAnchor.Method.EXACT
    assert anchor.quads == section_bboxes
    assert observation.section.stable_key == 'obligaciones-del-contratista'
    # The document author was told.
    assert Notification.objects.filter(
        user=context.users['editor'], event_key='observation.created'
    ).exists()


@pytest.mark.django_db
@pytest.mark.escenario('D3-F02')
def test_reply_from_the_author_moves_open_to_answered(with_v1):
    """A reply from someone other than the thread author moves the observation from open to answered."""
    context, document, v1 = with_v1
    observation = services.create_observation(
        v1, context.users['reviewer'], body='Falta el plazo de garantía.',
        section_key='obligaciones-del-contratista',
    )

    services.reply_to_observation(
        observation, context.users['editor'], 'Lo subimos al 5% en la próxima entrega.'
    )

    observation.refresh_from_db()
    assert observation.status == Observation.Status.ANSWERED
    reply = observation.replies.get()
    assert reply.status_change == 'open→answered'
    assert Notification.objects.filter(
        user=context.users['reviewer'], event_key='observation.replied'
    ).exists()


@pytest.mark.django_db
@pytest.mark.escenario('D3-F03')
def test_author_resolves_after_answered_with_version_recorded(with_v1):
    """set_observation_status records resolved_in_version when the thread author resolves an answered observation."""
    context, document, v1 = with_v1
    reviewer = context.users['reviewer']
    observation = services.create_observation(
        v1, reviewer, body='Multa baja.', section_key='obligaciones-del-contratista'
    )
    services.reply_to_observation(observation, context.users['editor'], 'Corregido.')

    services.set_observation_status(observation, reviewer, 'resolved')

    observation.refresh_from_db()
    assert observation.status == Observation.Status.RESOLVED
    assert observation.resolved_in_version is not None


@pytest.mark.django_db
@pytest.mark.escenario('D3-E01')
def test_i14_forbids_jumping_open_to_resolved(with_v1):
    """I14 forbids jumping directly from open to resolved, skipping answered."""
    context, _, v1 = with_v1
    observation = services.create_observation(
        v1, context.users['reviewer'], body='x', section_key='definiciones'
    )

    with pytest.raises(version_service.DomainError) as exc:
        services.set_observation_status(observation, context.users['reviewer'], 'resolved')

    assert exc.value.status_code == 409
    assert 'I14' in str(exc.value)


@pytest.mark.django_db
@pytest.mark.escenario('D3-E02')
def test_only_the_thread_author_or_admin_resolves(with_v1):
    """set_observation_status rejects resolution by a non-author, non-admin editor, but allows an admin."""
    context, _, v1 = with_v1
    observation = services.create_observation(
        v1, context.users['reviewer'], body='x', section_key='definiciones'
    )
    services.reply_to_observation(observation, context.users['editor'], 'listo')

    with pytest.raises(version_service.DomainError):
        services.set_observation_status(observation, context.users['editor'], 'resolved')

    # admin can
    services.set_observation_status(observation, context.users['admin'], 'resolved')
    observation.refresh_from_db()
    assert observation.status == Observation.Status.RESOLVED


@pytest.mark.django_db
@pytest.mark.escenario('D3-A01')
def test_resolved_thread_can_be_reopened(with_v1):
    """set_observation_status reopens a resolved thread back to open and clears resolved_in_version."""
    context, _, v1 = with_v1
    reviewer = context.users['reviewer']
    observation = services.create_observation(
        v1, reviewer, body='x', section_key='definiciones'
    )
    services.reply_to_observation(observation, context.users['editor'], 'listo')
    services.set_observation_status(observation, reviewer, 'resolved')

    services.set_observation_status(observation, reviewer, 'open')

    observation.refresh_from_db()
    assert observation.status == Observation.Status.OPEN
    assert observation.resolved_in_version is None


@pytest.mark.django_db
@pytest.mark.escenario('D3-F04')
@pytest.mark.escenario('D3-A03')
@pytest.mark.escenario('D3-A04')
def test_reanchor_truth_table_v1_to_v2(with_v1):
    """Re-anchoring on v2 follows the truth table for all three section fates.

    §3 modified ⇒ reanchored_section · §6 removed ⇒ orphaned · §1 intact ⇒
    exact carrying the original quads.
    """
    context, document, v1 = with_v1
    reviewer = context.users['reviewer']
    on_changed = services.create_observation(
        v1, reviewer, body='multas', section_key='obligaciones-del-contratista'
    )
    on_removed = services.create_observation(
        v1, reviewer, body='plazo', section_key='plazo-de-ejecucion'
    )
    on_intact = services.create_observation(
        v1, reviewer, body='objeto', section_key='objeto-del-contrato'
    )
    original_quads = on_intact.anchors.get().quads

    v2 = upload(document, 'contrato_v2.pdf', 'v2', context.users['editor'])

    changed_anchor = on_changed.anchors.get(document_version=v2)
    removed_anchor = on_removed.anchors.get(document_version=v2)
    intact_anchor = on_intact.anchors.get(document_version=v2)
    v2_section_bboxes = SectionVersion.objects.get(
        document_version=v2, section__stable_key='obligaciones-del-contratista'
    ).bboxes
    assert changed_anchor.method == ObservationAnchor.Method.REANCHORED
    assert changed_anchor.quads == v2_section_bboxes
    # Proves the coordinates actually moved — not silently carried over stale.
    assert changed_anchor.quads != on_changed.anchors.get(document_version=v1).quads
    assert removed_anchor.method == ObservationAnchor.Method.ORPHANED
    assert removed_anchor.quads == []
    assert intact_anchor.method == ObservationAnchor.Method.EXACT
    assert intact_anchor.quads == original_quads


@pytest.mark.django_db
@pytest.mark.escenario('D3-A02')
def test_reanchor_is_idempotent(with_v1):
    """reanchor_observations is idempotent: re-running it on the same version creates no duplicate anchors."""
    context, document, v1 = with_v1
    services.create_observation(
        v1, context.users['reviewer'], body='x', section_key='objeto-del-contrato'
    )
    v2 = upload(document, 'contrato_v2.pdf', 'v2', context.users['editor'])

    counters = services.reanchor_observations(v2)  # re-run

    assert counters == {'exact': 0, 'reanchored_section': 0, 'orphaned': 0}
    assert ObservationAnchor.objects.filter(document_version=v2).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('D3-E03')
def test_observation_on_unknown_section_is_rejected(with_v1):
    """create_observation rejects a section_key that does not exist on the version."""
    context, _, v1 = with_v1

    with pytest.raises(version_service.DomainError):
        services.create_observation(
            v1, context.users['reviewer'], body='x', section_key='no-existe'
        )


@pytest.mark.django_db
@pytest.mark.parametrize(('actor', 'expected'), [
    pytest.param('reviewer', 201, id='d3-p01-reviewer'),
    pytest.param('admin', 201, id='d3-p01-admin'),
    pytest.param('editor', 404, id='d3-p02-editor-hidden'),
    pytest.param('viewer', 404, id='d3-p02-viewer-hidden'),
    pytest.param('anonymous', 401, id='d3-p03-anonymous'),
    pytest.param('non_member', 404, id='d3-p04-non-member'),
])
@pytest.mark.escenario('D3-P01')
def test_create_observation_permission_matrix(client_as, with_v1, actor, expected):
    """The create-observation endpoint enforces the DRF permission matrix per role."""
    _, _, v1 = with_v1

    response = client_as(actor).post(
        f'/api/versions/{v1.public_id}/observations/',
        {'body': 'obs', 'section_key': 'definiciones'},
        format='json',
    )

    assert response.status_code == expected


@pytest.mark.django_db
def test_observations_list_shows_thread_with_anchors_via_api(client_as, with_v1):
    """The observations list returns the current anchor without materializing history."""
    context, document, v1 = with_v1
    services.create_observation(
        v1, context.users['reviewer'], body='multa baja',
        section_key='obligaciones-del-contratista',
    )
    upload(document, 'contrato_v2.pdf', 'v2', context.users['editor'])
    v2 = document.versions.get(number=2)

    response = client_as('viewer').get(f'/api/versions/{v2.public_id}/observations/')

    assert response.status_code == 200
    thread = response.data['results'][0]
    assert thread['status'] == 'open'
    assert thread['current_anchor']['version_number'] == 2
    assert thread['current_anchor']['method'] == 'reanchored_section'
    assert thread['current_anchor']['quads_content_url'].endswith('/content/')
    assert 'anchors' not in thread
