"""Seal endpoints: happy paths + permission matrices (docs/audit/03 D4/D5 P)."""

from pathlib import Path

import pytest
from audit.models import AuditEvent
from django.utils import timezone
from documents.services import storage_service, version_service

from reviews.models import Seal
from reviews.services import seal_service

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


@pytest.fixture
def analyzed_v1(versiona_context):
    """Create a document whose first PDF version completed analysis."""
    editor = versiona_context.users['editor']
    document = version_service.create_document(versiona_context.project, 'Sellable', editor)
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf'
    )
    version, _ = version_service.complete_upload(document, intent.upload_id, 'v1', editor)
    return versiona_context, document, version


def seals_url(version):
    """Return the seal collection route for one version."""
    return f'/api/versions/{version.public_id}/seals/'


@pytest.mark.django_db
@pytest.mark.escenario('D4-F01')
def test_reviewer_places_a_section_seal_via_api(client_as, analyzed_v1):
    """A reviewer can seal the selected section through the API."""
    _, _, version = analyzed_v1

    response = client_as('reviewer').post(
        seals_url(version),
        {'covers_all': False, 'section_keys': ['objeto-del-contrato']},
        format='json',
    )

    assert response.status_code == 201
    assert response.data['covered_keys'] == ['objeto-del-contrato']
    assert response.data['is_active'] is True
    assert response.data['key_id']


@pytest.mark.django_db
@pytest.mark.escenario('D4-E02')
def test_sealing_unknown_sections_is_rejected(client_as, analyzed_v1):
    """An unknown section key produces a readable validation rejection."""
    _, _, version = analyzed_v1

    response = client_as('reviewer').post(
        seals_url(version),
        {'covers_all': False, 'section_keys': ['seccion-fantasma']},
        format='json',
    )

    assert response.status_code == 400
    assert 'fantasma' in response.data['error']


@pytest.mark.django_db
@pytest.mark.escenario('D4-E03')
def test_double_active_seal_by_the_same_reviewer_is_rejected(client_as, analyzed_v1):
    """A reviewer cannot create a second active seal on the same version."""
    _, _, version = analyzed_v1
    client = client_as('reviewer')
    client.post(seals_url(version), {'covers_all': True}, format='json')

    response = client.post(seals_url(version), {'covers_all': True}, format='json')

    assert response.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('D4-E01')
def test_sealing_a_superseded_version_via_api_is_rejected(client_as, analyzed_v1):
    """Catches: the viewer's seal action approving a version that a newer
    upload superseded (I10)."""
    context, document, v1 = analyzed_v1
    editor = context.users['editor']
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v2.pdf').read_bytes(), 'application/pdf'
    )
    version_service.complete_upload(document, intent.upload_id, 'v2', editor)

    response = client_as('reviewer').post(seals_url(v1), {'covers_all': True}, format='json')

    assert response.status_code == 409
    assert response.data['error'] == 'Solo se puede sellar la versión vigente del documento.'


@pytest.mark.django_db
@pytest.mark.escenario('D4-F03')
def test_verify_endpoint_returns_offline_verification_material(client_as, analyzed_v1):
    """Verification exposes the material needed to validate a seal offline."""
    context, _, version = analyzed_v1
    seal = seal_service.create_seal(version, context.users['reviewer'], covers_all=True)

    response = client_as('viewer').get(
        f'{seals_url(version)}{seal.public_id}/verify/'
    )

    assert response.status_code == 200
    assert response.data['signature_valid'] is True
    assert response.data['binds_version_sha256'] is True
    assert response.data['algorithm'] == 'Ed25519'
    assert response.data['public_key']


@pytest.mark.django_db
def test_verify_endpoint_reports_invalid_for_a_tampered_stored_signature(client_as, analyzed_v1):
    """Report a corrupted stored signature independently of the version binding.

    The stored payload remains unchanged while its signature is corrupted.
    A successful HTTP response must still report signature_valid=False (I6).
    """
    from reviews.models import Seal

    context, _, version = analyzed_v1
    seal = seal_service.create_seal(version, context.users['reviewer'], covers_all=True)
    Seal.objects.filter(pk=seal.pk).update(signature='QUFBQQ==')

    response = client_as('viewer').get(
        f'{seals_url(version)}{seal.public_id}/verify/'
    )

    assert response.status_code == 200
    assert response.data['signature_valid'] is False
    # The stored payload itself was untouched — proves the two signals are
    # independent: a corrupted SIGNATURE alone must not silently also flip
    # binds_version_sha256, which would mask which check actually failed.
    assert response.data['binds_version_sha256'] is True


@pytest.mark.django_db
def test_public_key_endpoint_serves_the_current_key(client_as, analyzed_v1):
    """The public-key route returns the current signing key material."""
    from reviews.services import signing

    response = client_as('viewer').get(f'/api/seal_keys/{signing.key_id()}/')

    assert response.status_code == 200
    assert response.data['public_key'] == signing.public_key_b64()


@pytest.mark.django_db
@pytest.mark.parametrize(('actor', 'expected'), [
    pytest.param('reviewer', 201, id='d4-p01-reviewer'),
    pytest.param('admin', 201, id='d4-p01-admin'),
    pytest.param('editor', 404, id='d4-p02-editor-hidden'),
    pytest.param('viewer', 404, id='d4-p02-viewer-hidden'),
    pytest.param('anonymous', 401, id='d4-p03-anonymous'),
    pytest.param('non_member', 404, id='d4-p04-non-member'),
])
@pytest.mark.escenario('D4-P01')
def test_place_seal_permission_matrix(client_as, analyzed_v1, actor, expected):
    """Seal creation honors the permission outcome for each actor."""
    _, _, version = analyzed_v1

    response = client_as(actor).post(
        seals_url(version), {'covers_all': True}, format='json'
    )

    assert response.status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize(('actor', 'expected'), [
    pytest.param('viewer', 200, id='d4-list-p01-viewer'),
    pytest.param('anonymous', 401, id='d4-list-p03-anonymous'),
    pytest.param('non_member', 404, id='d4-list-p04-non-member'),
])
def test_list_seals_permission_matrix(client_as, analyzed_v1, actor, expected):
    """Seal listing honors the permission outcome for each actor."""
    _, _, version = analyzed_v1

    response = client_as(actor).get(seals_url(version))

    assert response.status_code == expected


@pytest.mark.django_db
@pytest.mark.escenario('D5-F07')
def test_seals_listing_includes_validity_records_of_incoming_version(client_as, analyzed_v1):
    """The target-version listing includes its incoming invalidation evidence."""
    context, document, v1 = analyzed_v1
    editor = context.users['editor']
    seal_service.create_seal(v1, context.users['reviewer'],
                             section_keys=['obligaciones-del-contratista'])
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v2.pdf').read_bytes(), 'application/pdf'
    )
    v2, _ = version_service.complete_upload(document, intent.upload_id, 'v2', editor)

    response = client_as('viewer').get(seals_url(v2))

    assert response.status_code == 200
    records = response.data['validity_records']
    assert len(records) == 1
    assert records[0]['decision'] == 'invalidated'
    assert records[0]['reason_code'] == 'section_modified'
    assert records[0]['seal']['reviewer_email'] == context.users['reviewer'].email


@pytest.mark.django_db
@pytest.mark.parametrize(('project_state', 'expected_status'), [('archived', 409), ('trashed', 404)])
def test_readonly_project_rejects_seal_withdrawal_via_api(
    client_as, analyzed_v1, project_state, expected_status,
):
    """Catches: exposing a write surface on archival or revealing a trashed project."""
    context, _, version = analyzed_v1
    seal = seal_service.create_seal(
        version, context.users['reviewer'], section_keys=['objeto-del-contrato'],
    )
    project = version.document.project
    project.status = {'archived': 'archived', 'trashed': 'active'}[project_state]
    project.deleted_at = {'archived': None, 'trashed': timezone.now()}[project_state]
    project.save(update_fields=['status', 'deleted_at'])
    audit_count = AuditEvent.objects.count()

    response = client_as('reviewer').post(f'{seals_url(version)}{seal.public_id}/revoke/')

    assert response.status_code == expected_status
    seal.refresh_from_db()
    assert seal.revoked_at is None
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_archived_seal_withdrawal_preserves_the_author_permission_error(client_as, analyzed_v1):
    """Catches: the readonly guard replacing the existing foreign-author 403."""
    context, _, version = analyzed_v1
    seal = seal_service.create_seal(
        version, context.users['reviewer'], section_keys=['objeto-del-contrato'],
    )
    project = version.document.project
    project.status = 'archived'
    project.save(update_fields=['status'])

    response = client_as('admin').post(f'{seals_url(version)}{seal.public_id}/revoke/')

    assert response.status_code == 403
    assert response.data == {'error': 'Solo el autor del sello puede retirarlo.'}
    assert Seal.objects.get(pk=seal.pk).revoked_at is None
