"""D1 request endpoint edges + service validations over engine-independent
fixtures (versions arrive analyzed from the shared context)."""

from uuid import uuid4

import pytest
from audit.models import AuditEvent
from django.urls import Resolver404, resolve

from documents.models import DocumentVersion
from documents.services.version_service import DomainError
from notifications.models import Notification
from orgs.models import OrganizationMembership
from projects.models import ProjectMembership
from projects.services import config_service
from reviews.models import ReviewAssignment, ReviewRequest
from reviews.services import review_service


@pytest.fixture
def ready_version(document_with_versions):
    document, versions = document_with_versions(n_versions=1)
    return document, versions[0]


@pytest.fixture
def open_review(ready_version, versiona_context):
    _, version = ready_version
    return review_service.create_review_request(
        version, versiona_context.users['editor'],
        [versiona_context.users['reviewer'].pk],
        message='prioridad multas',
    )


@pytest.mark.django_db
@pytest.mark.escenario('D1-F01')
def test_reviews_list_returns_requests_with_assignments(
    client_as, ready_version, versiona_context, open_review
):
    _, version = ready_version

    response = client_as('viewer').get(f'/api/versions/{version.public_id}/reviews/')

    assert response.status_code == 200
    row = response.data['results'][0]
    assert row['status'] == 'open'
    assert row['assignments'][0]['reviewer_email'] == versiona_context.users['reviewer'].email


@pytest.mark.django_db
@pytest.mark.escenario('D1-E02')
def test_second_open_request_via_api_returns_conflict(
    client_as, ready_version, versiona_context, open_review
):
    _, version = ready_version

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/',
        {'reviewer_ids': [versiona_context.users['reviewer'].pk]},
        format='json',
    )

    assert response.status_code == 409
    assert response.data['error'] == 'Esta versión ya tiene una revisión abierta.'


@pytest.mark.django_db
@pytest.mark.escenario('D1-A02')
def test_requester_cancels_open_review_via_api(client_as, ready_version, open_review):
    _, version = ready_version

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/{open_review.public_id}/cancel/'
    )

    assert response.status_code == 200
    assert response.data['status'] == 'cancelled'
    open_review.refresh_from_db()
    assert open_review.closed_at is not None


@pytest.mark.django_db
@pytest.mark.escenario('D1-P04')
def test_cancel_unknown_review_returns_404(client_as, ready_version):
    _, version = ready_version

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/{uuid4()}/cancel/'
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.escenario('D1-A02')
def test_cancel_already_closed_review_returns_conflict(
    client_as, ready_version, versiona_context, open_review
):
    _, version = ready_version
    review_service.cancel_review_request(open_review, versiona_context.users['editor'])

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/{open_review.public_id}/cancel/'
    )

    assert response.status_code == 409
    assert response.data['error'] == 'La solicitud ya está cerrada.'


@pytest.mark.django_db
@pytest.mark.escenario('D2-L01')
def test_review_context_endpoint_returns_empty_payload_without_seal(client_as, ready_version):
    _, version = ready_version

    response = client_as('reviewer').get(f'/api/versions/{version.public_id}/review_context/')

    assert response.status_code == 200
    assert response.data == {'my_last_sealed_version': None, 'changed': [], 'unchanged': []}


@pytest.mark.django_db
@pytest.mark.escenario('D1-E01')
def test_review_request_requires_analyzed_version(ready_version, versiona_context):
    _, version = ready_version
    DocumentVersion.all_objects.filter(pk=version.pk).update(
        analysis_status=DocumentVersion.AnalysisStatus.PENDING
    )
    version.refresh_from_db()

    with pytest.raises(DomainError) as excinfo:
        review_service.create_review_request(
            version, versiona_context.users['editor'],
            [versiona_context.users['reviewer'].pk],
        )

    assert excinfo.value.status_code == 409
    assert str(excinfo.value) == 'Solo se puede solicitar revisión de una versión analizada.'


@pytest.mark.django_db
@pytest.mark.escenario('D1-E01')
def test_review_request_on_trashed_version_is_rejected(ready_version, versiona_context):
    _, version = ready_version
    version.soft_delete(versiona_context.users['editor'])

    with pytest.raises(DomainError) as excinfo:
        review_service.create_review_request(
            version, versiona_context.users['editor'],
            [versiona_context.users['reviewer'].pk],
        )

    assert excinfo.value.status_code == 409
    assert str(excinfo.value) == 'La versión está en la papelera.'


@pytest.mark.django_db
@pytest.mark.escenario('D1-E01')
def test_review_request_without_reviewers_is_rejected(ready_version, versiona_context):
    _, version = ready_version

    with pytest.raises(DomainError) as excinfo:
        review_service.create_review_request(version, versiona_context.users['editor'], [])

    assert excinfo.value.status_code == 400
    assert str(excinfo.value) == 'Elige al menos un revisor.'


@pytest.mark.django_db
@pytest.mark.escenario('D1-E01')
def test_review_request_with_unknown_reviewer_is_rejected(ready_version, versiona_context):
    """Unknown reviewer IDs share the privacy rejection of inaccessible users."""
    _, version = ready_version

    with pytest.raises(DomainError) as excinfo:
        review_service.create_review_request(
            version, versiona_context.users['editor'], [999999]
        )

    assert excinfo.value.status_code == 404
    assert str(excinfo.value) == 'Revisor no encontrado.'


def review_selection_state(version):
    """Capture persistent effects and the version preserved by a rejected selection."""
    return {
        'requests': ReviewRequest.objects.count(),
        'assignments': ReviewAssignment.objects.count(),
        'notifications': Notification.objects.count(),
        'audit_events': AuditEvent.objects.count(),
        'version': DocumentVersion.objects.values(
            'message', 'sha256', 'analysis_status', 'config_version_id', 'is_approved',
        ).get(pk=version.pk),
    }


@pytest.fixture(params=['foreign', 'without_project', 'inactive_org', 'unknown'])
def hidden_reviewer_id(request, versiona_context, django_user_model):
    """Supply IDs unavailable through the target project's effective access."""
    if request.param == 'foreign':
        return versiona_context.users['non_member'].pk
    if request.param == 'without_project':
        user = django_user_model.objects.create_user(
            email='unassigned@versiona.test', password='secreta123',
        )
        OrganizationMembership.objects.create(
            organization=versiona_context.org, user=user,
            role=OrganizationMembership.Role.MEMBER,
        )
        return user.pk
    if request.param == 'inactive_org':
        user = versiona_context.users['reviewer']
        OrganizationMembership.objects.filter(
            organization=versiona_context.org, user=user,
        ).update(is_active=False)
        return user.pk
    return 999999


@pytest.mark.django_db
def test_hidden_reviewer_returns_uniform_not_found(
    client_as, ready_version, hidden_reviewer_id,
):
    """Unavailable reviewer IDs reveal no identity and leave persistent state intact."""
    _, version = ready_version
    before = review_selection_state(version)

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/',
        {'reviewer_ids': [hidden_reviewer_id]}, format='json',
    )

    assert response.status_code == 404
    assert response.data == {'error': 'Revisor no encontrado.'}
    assert review_selection_state(version) == before


@pytest.mark.django_db
@pytest.mark.parametrize(('visible_alias', 'hidden_first'), [
    pytest.param('viewer', False, id='viewer-before-hidden'),
    pytest.param('viewer', True, id='hidden-before-viewer'),
    pytest.param('admin', False, id='self-before-hidden'),
    pytest.param('admin', True, id='hidden-before-self'),
])
def test_hidden_reviewer_precedes_visible_selection_errors(
    client_as, ready_version, versiona_context, visible_alias, hidden_first,
):
    """A mixed selection has one privacy response regardless of candidate order."""
    _, version = ready_version
    visible_id = versiona_context.users[visible_alias].pk
    hidden_id = versiona_context.users['non_member'].pk
    reviewer_ids = {False: [visible_id, hidden_id], True: [hidden_id, visible_id]}[hidden_first]
    before = review_selection_state(version)

    response = client_as('admin').post(
        f'/api/versions/{version.public_id}/reviews/',
        {'reviewer_ids': reviewer_ids}, format='json',
    )

    assert response.status_code == 404
    assert response.data == {'error': 'Revisor no encontrado.'}
    assert review_selection_state(version) == before


@pytest.mark.django_db
@pytest.mark.parametrize(('visible_alias', 'expected_error'), [
    pytest.param(
        'viewer', 'viewer@versiona.test no puede revisar en este proyecto (rol: viewer).',
        id='visible-viewer',
    ),
    pytest.param('admin', 'No puedes asignarte tu propia revisión.', id='visible-self'),
])
def test_visible_reviewer_keeps_selection_error(
    client_as, ready_version, versiona_context, visible_alias, expected_error,
):
    """Visible candidates retain their actionable role or self-review rejection."""
    _, version = ready_version
    before = review_selection_state(version)

    response = client_as('admin').post(
        f'/api/versions/{version.public_id}/reviews/',
        {'reviewer_ids': [versiona_context.users[visible_alias].pk]}, format='json',
    )

    assert response.status_code == 400
    assert response.data == {'error': expected_error}
    assert review_selection_state(version) == before


@pytest.mark.django_db
@pytest.mark.parametrize('org_role', ['owner', 'admin'])
def test_implicit_org_admin_can_receive_review_assignment(
    client_as, ready_version, versiona_context, org_role,
):
    """Effective organization admins remain eligible without project membership."""
    _, version = ready_version
    reviewer = versiona_context.users['owner']
    OrganizationMembership.objects.filter(
        organization=versiona_context.org, user=reviewer,
    ).update(role=org_role)
    assert not ProjectMembership.objects.filter(
        project=versiona_context.project, user=reviewer,
    ).exists()

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/',
        {'reviewer_ids': [reviewer.pk]}, format='json',
    )

    assert response.status_code == 201
    review = ReviewRequest.objects.get(public_id=response.data['public_id'])
    assert review.document_version_id == version.pk
    assert review.requested_by_id == versiona_context.users['editor'].pk
    assignment = review.assignments.get()
    assert assignment.reviewer_id == reviewer.pk
    assert assignment.status == ReviewAssignment.Status.PENDING
    notification = Notification.objects.get(user=reviewer, event_key='review.requested')
    assert notification.payload['review'] == str(review.public_id)
    event = AuditEvent.objects.get(event_type='review.requested', object_id_ref=str(review.public_id))
    assert event.payload['reviewers'] == [reviewer.email]


@pytest.mark.django_db
@pytest.mark.escenario('D1-A02')
def test_non_requester_reviewer_cannot_cancel_review(versiona_context, open_review):
    with pytest.raises(DomainError) as excinfo:
        review_service.cancel_review_request(open_review, versiona_context.users['reviewer'])

    assert excinfo.value.status_code == 403
    assert str(excinfo.value) == 'Solo quien la abrió (o un admin) puede cancelarla.'


@pytest.mark.django_db
@pytest.mark.escenario('D1-A02')
def test_admin_who_did_not_request_can_cancel_review(versiona_context, open_review):
    review = review_service.cancel_review_request(open_review, versiona_context.users['admin'])

    assert review.status == ReviewRequest.Status.CANCELLED


@pytest.fixture
def version_owned_by_sections(versiona_context, document_with_versions):
    """Project config carrying section owners (B3) pinned on an analyzed version."""
    versiona_context.config = config_service.update_config(
        versiona_context.project,
        versiona_context.users['admin'],
        section_owners={
            'objeto-del-contrato': [versiona_context.users['reviewer'].pk],
            'confidencialidad': [versiona_context.users['admin'].pk],
        },
    )
    _, versions = document_with_versions(n_versions=1)
    return versions[0]


@pytest.mark.django_db
@pytest.mark.escenario('D1-A01')
def test_section_owners_do_not_make_reviewer_selection_optional(
    client_as, version_owned_by_sections
):
    """Negative verification: auto-suggestion from section owners is absent —
    the request still demands an explicit manual selection (DP-A7)."""
    version = version_owned_by_sections

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/', {}, format='json'
    )

    assert response.status_code == 400
    assert 'reviewer_ids' in response.data


@pytest.mark.django_db
@pytest.mark.escenario('D1-A01')
def test_section_owners_are_not_added_as_reviewers_on_their_own(
    client_as, versiona_context, version_owned_by_sections
):
    """Negative verification: the admin owns 'confidencialidad' yet gets no
    assignment because only the explicitly chosen reviewer is assigned."""
    version = version_owned_by_sections

    response = client_as('editor').post(
        f'/api/versions/{version.public_id}/reviews/',
        {'reviewer_ids': [versiona_context.users['reviewer'].pk]},
        format='json',
    )

    assert response.status_code == 201
    assigned = {row['reviewer_email'] for row in response.data['assignments']}
    assert assigned == {versiona_context.users['reviewer'].email}


@pytest.mark.django_db
@pytest.mark.escenario('D1-A01')
def test_assignment_scope_ignores_the_sections_the_reviewer_owns(
    versiona_context, version_owned_by_sections
):
    """Negative verification: no per-section scope is derived from ownership —
    every assignment is created covering the whole document."""
    review = review_service.create_review_request(
        version_owned_by_sections,
        versiona_context.users['editor'],
        [versiona_context.users['reviewer'].pk],
    )

    assert review.assignments.get().scope == 'all'


@pytest.mark.django_db
@pytest.mark.escenario('D2-P01')
def test_review_progress_route_is_not_registered():
    """Negative verification: `review_requests/{id}/progress/` (docs/audit/03 D2)
    has no URL entry, so its permission matrix cannot exist yet."""
    with pytest.raises(Resolver404):
        resolve(f'/api/review_requests/{uuid4()}/progress/')


@pytest.mark.django_db
@pytest.mark.escenario('D2-P01')
def test_assigned_reviewer_hits_a_missing_progress_endpoint(client_as, open_review):
    """Negative verification: even the assigned reviewer gets a router 404 —
    the D2 progress surface is unimplemented, not merely restricted."""
    assignment = ReviewAssignment.objects.get(review_request=open_review)

    response = client_as('reviewer').get(
        f'/api/review_requests/{assignment.review_request.public_id}/progress/'
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize('actor, expected', [
    pytest.param('reviewer', 200, id='d2-p01-assigned-reviewer'),
    pytest.param('viewer', 200, id='d2-p02-unassigned-member'),
    pytest.param('anonymous', 401, id='d2-p03-anonymous'),
    pytest.param('non_member', 404, id='d2-p04-non-member'),
])
@pytest.mark.escenario('D2-P01')
def test_review_context_permission_matrix(client_as, ready_version, open_review, actor, expected):
    """The implemented D2 surface is `review_context/`, gated by project role
    (viewer+), not by assignment: an unassigned member reads it too."""
    _, version = ready_version

    response = client_as(actor).get(f'/api/versions/{version.public_id}/review_context/')

    assert response.status_code == expected
