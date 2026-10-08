"""D5 coordinator mode: pending plan + confirmation via API (DP-07)."""

from pathlib import Path

import pytest
from audit.models import AuditEvent
from django.utils import timezone

from documents.services import storage_service, version_service
from notifications.models import Notification
from projects.models import ProjectConfigVersion
from reviews.models import SealValidityRecord
from reviews.services import seal_service

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


@pytest.fixture
def pending_plan(versiona_context):
    """Project in coordinator mode with a sealed §3 and a v2 that changes it."""
    context = versiona_context
    config = ProjectConfigVersion.current_for(context.project)
    ProjectConfigVersion.objects.create(
        project=context.project, number=config.number + 1,
        d5_mode=ProjectConfigVersion.D5Mode.COORDINATOR,
        approval_policy=config.approval_policy,
    )
    editor = context.users['editor']
    document = version_service.create_document(context.project, 'Coordinado', editor)

    def push(fixture, message):
        intent = version_service.create_upload_intent(document, editor)
        storage_service.put_bytes(
            intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf'
        )
        version, _ = version_service.complete_upload(document, intent.upload_id, message, editor)
        return version

    v1 = push('contrato_v1.pdf', 'v1')
    seal = seal_service.create_seal(
        v1, context.users['reviewer'], section_keys=['obligaciones-del-contratista']
    )
    v2 = push('contrato_v2.pdf', 'v2')
    return context, v2, seal


def plan_url(version):
    return f'/api/versions/{version.public_id}/seal_plan/'


@pytest.mark.django_db
@pytest.mark.escenario('D5-A04')
def test_coordinator_mode_leaves_the_decision_pending_and_notifies_admins(pending_plan):
    context, v2, seal = pending_plan

    record = SealValidityRecord.objects.get(seal=seal)
    assert record.decision == SealValidityRecord.Decision.PENDING
    assert record.proposed_decision == SealValidityRecord.Decision.INVALIDATED
    # The reviewer is NOT notified while the plan is pending…
    assert not Notification.objects.filter(
        user=seal.reviewer, event_key='seal.invalidated'
    ).exists()
    # …the admins are.
    assert Notification.objects.filter(
        user=context.users['admin'], event_key='seal_plan.pending'
    ).exists()


@pytest.mark.django_db
@pytest.mark.escenario('D5-A04')
def test_admin_confirms_the_plan_and_the_reviewer_is_then_notified(client_as, pending_plan):
    context, v2, seal = pending_plan

    response = client_as('admin').post(
        plan_url(v2),
        {'decisions': {str(seal.public_id): 'invalidated'}},
        format='json',
    )

    assert response.status_code == 200
    record = SealValidityRecord.objects.get(seal=seal)
    assert record.decision == SealValidityRecord.Decision.INVALIDATED
    assert record.decided_mode == SealValidityRecord.Mode.COORDINATOR
    assert record.decided_by == context.users['admin']
    assert Notification.objects.filter(
        user=seal.reviewer, event_key='seal.invalidated'
    ).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('D5-A06')
def test_coordinator_can_preserve_explicitly_and_it_stays_on_the_record(client_as, pending_plan):
    context, v2, seal = pending_plan

    response = client_as('admin').post(
        plan_url(v2),
        {'decisions': {str(seal.public_id): 'preserved'}},
        format='json',
    )

    assert response.status_code == 200
    record = SealValidityRecord.objects.get(seal=seal)
    assert record.decision == SealValidityRecord.Decision.PRESERVED
    # The audit trail keeps what the machine proposed vs what the human chose.
    assert record.proposed_decision == SealValidityRecord.Decision.INVALIDATED
    assert seal_service.seal_is_valid_at(seal, v2) is True


@pytest.mark.django_db
def test_confirming_without_a_decision_per_seal_is_rejected(client_as, pending_plan):
    _, v2, _ = pending_plan

    response = client_as('admin').post(plan_url(v2), {'decisions': {}}, format='json')

    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize('actor, expected', [
    pytest.param('admin', 200, id='d5-plan-p01-admin'),
    pytest.param('reviewer', 404, id='d5-plan-p02-reviewer-hidden'),
    pytest.param('editor', 404, id='d5-plan-p02-editor-hidden'),
    pytest.param('anonymous', 401, id='d5-plan-p03-anonymous'),
    pytest.param('non_member', 404, id='d5-plan-p04-non-member'),
])
@pytest.mark.escenario('D5-P01')
def test_confirm_plan_permission_matrix(client_as, pending_plan, actor, expected):
    _, v2, seal = pending_plan

    response = client_as(actor).post(
        plan_url(v2),
        {'decisions': {str(seal.public_id): 'invalidated'}},
        format='json',
    )

    assert response.status_code == expected


@pytest.mark.django_db
def test_pending_plan_listing_is_visible_to_members(client_as, pending_plan):
    _, v2, seal = pending_plan

    response = client_as('viewer').get(plan_url(v2))

    assert response.status_code == 200
    assert len(response.data['pending']) == 1
    assert response.data['pending'][0]['proposed_decision'] == 'invalidated'


@pytest.mark.django_db
@pytest.mark.parametrize('second_choice', ['invalidated', 'preserved'])
def test_second_confirmation_preserves_the_first_final_record(client_as, pending_plan, second_choice):
    """Catches: retrying a completed plan rewriting its actor, timestamp or effects."""
    _, version, seal = pending_plan
    client = client_as('admin')
    first = client.post(
        plan_url(version), {'decisions': {str(seal.public_id): 'invalidated'}}, format='json',
    )
    original = SealValidityRecord.objects.get(seal=seal)
    snapshot = (original.decision, original.decided_by_id, original.decided_at)
    audit_count = AuditEvent.objects.count()
    notice_count = Notification.objects.count()

    second = client.post(
        plan_url(version), {'decisions': {str(seal.public_id): second_choice}}, format='json',
    )

    assert first.status_code == 200
    assert second.status_code == 404
    assert second.data == {'error': 'No hay plan de invalidación pendiente en esta versión.'}
    original.refresh_from_db()
    assert (original.decision, original.decided_by_id, original.decided_at) == snapshot
    assert AuditEvent.objects.count() == audit_count
    assert Notification.objects.count() == notice_count


@pytest.mark.django_db
def test_archived_project_rejects_plan_confirmation(client_as, pending_plan):
    """Catches: coordinator finalizing a plan while its project is readonly."""
    _, version, seal = pending_plan
    project = version.document.project
    project.status = 'archived'
    project.save(update_fields=['status'])
    audit_count = AuditEvent.objects.count()
    notice_count = Notification.objects.count()

    response = client_as('admin').post(
        plan_url(version), {'decisions': {str(seal.public_id): 'invalidated'}}, format='json',
    )

    assert response.status_code == 409
    assert response.data == {'error': 'El proyecto está archivado o en la papelera: es de solo lectura.'}
    record = SealValidityRecord.objects.get(seal=seal)
    assert (record.decision, record.decided_by_id, record.decided_at) == ('pending_confirmation', None, None)
    assert AuditEvent.objects.count() == audit_count
    assert Notification.objects.count() == notice_count


@pytest.mark.django_db
def test_trashed_project_rejects_plan_confirmation_in_the_service(pending_plan):
    """Catches: a direct service caller bypassing the project's trash guard."""
    context, version, seal = pending_plan
    project = version.document.project
    project.deleted_at = timezone.now()
    project.save(update_fields=['deleted_at'])
    audit_count = AuditEvent.objects.count()
    notice_count = Notification.objects.count()

    with pytest.raises(version_service.DomainError) as exc:
        seal_service.confirm_seal_plan(version, context.users['admin'], {str(seal.public_id): 'invalidated'})

    assert exc.value.status_code == 409
    record = SealValidityRecord.objects.get(seal=seal)
    assert (record.decision, record.decided_by_id, record.decided_at) == ('pending_confirmation', None, None)
    assert AuditEvent.objects.count() == audit_count
    assert Notification.objects.count() == notice_count


@pytest.mark.django_db
def test_restored_project_allows_plan_confirmation(client_as, pending_plan):
    """Catches: archival permanently disabling a pending coordinator decision."""
    _, version, seal = pending_plan
    project = version.document.project
    project.status = 'archived'
    project.save(update_fields=['status'])
    client = client_as('admin')
    rejected = client.post(
        plan_url(version), {'decisions': {str(seal.public_id): 'invalidated'}}, format='json',
    )
    project.status = 'active'
    project.save(update_fields=['status'])

    response = client.post(
        plan_url(version), {'decisions': {str(seal.public_id): 'invalidated'}}, format='json',
    )

    assert rejected.status_code == 409
    assert response.status_code == 200
    assert SealValidityRecord.objects.get(seal=seal).decision == 'invalidated'
