"""A1: wizard + sample project seed → the wow link (metric S1)."""

from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from accounts.views import auth as auth_views
from documents.services import storage_service
from orgs.models import Organization, OrganizationMembership
from orgs.onboarding import complete_onboarding, onboarding_state
from orgs.services import ensure_personal_org

GOOGLE_EMAIL = 'nueva.google@versiona.test'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


@pytest.fixture
def fresh_user(django_user_model):
    user = django_user_model.objects.create_user(
        email='nueva@versiona.test', password='secreta123', first_name='Nueva'
    )
    ensure_personal_org(user)
    return user


@pytest.fixture
def google_signup(api_client, monkeypatch, settings):
    settings.DEBUG = False
    settings.GOOGLE_OAUTH_CLIENT_ID = 'client-1'
    tokeninfo = Mock(status_code=200, text='')
    tokeninfo.json = Mock(return_value={
        'aud': 'client-1',
        'email': GOOGLE_EMAIL,
        'email_verified': True,
        'given_name': 'Nueva',
        'family_name': 'Google',
    })
    monkeypatch.setattr(auth_views.requests, 'get', Mock(return_value=tokeninfo))

    def _signup():
        return api_client.post(
            '/api/google_login/', {'credential': 'token-google'}, format='json'
        )

    return _signup


@pytest.fixture
def failing_storage(monkeypatch):
    monkeypatch.setattr(
        storage_service, 'put_bytes', Mock(side_effect=RuntimeError('storage caído'))
    )
    return monkeypatch


@pytest.mark.django_db
@pytest.mark.escenario('A1-A01')
def test_google_signup_provisions_the_personal_org(google_signup, django_user_model):
    google_signup()

    user = django_user_model.objects.get(email=GOOGLE_EMAIL)
    membership = OrganizationMembership.objects.get(user=user)
    assert membership.role == OrganizationMembership.Role.OWNER
    assert membership.organization.kind == Organization.Kind.PERSONAL


@pytest.mark.django_db
@pytest.mark.escenario('A1-A01')
def test_google_signup_leaves_the_onboarding_wizard_pending(
    google_signup, django_user_model
):
    google_signup()

    user = django_user_model.objects.get(email=GOOGLE_EMAIL)
    client = APIClient()
    client.force_authenticate(user)
    state = client.get('/api/me/onboarding/')
    assert state.status_code == 200
    assert state.data['status'] == 'pending'


@pytest.mark.django_db
@pytest.mark.escenario('A1-E01')
def test_failed_seed_job_leaves_the_wizard_pending_for_a_retry(
    fresh_user, failing_storage
):
    with pytest.raises(RuntimeError):
        complete_onboarding(fresh_user, 'Constructora Nueva')

    assert onboarding_state(fresh_user)['status'] == 'pending'


@pytest.mark.django_db
@pytest.mark.escenario('A1-E01')
def test_failed_seed_job_leaves_no_half_seeded_sample_project(
    fresh_user, failing_storage
):
    from projects.models import Project

    with pytest.raises(RuntimeError):
        complete_onboarding(fresh_user, 'Constructora Nueva')

    assert Project.objects.filter(is_sample=True).count() == 0


@pytest.mark.django_db
@pytest.mark.escenario('A1-E01')
def test_retry_after_a_failed_seed_job_completes_the_sample(fresh_user, failing_storage):
    with pytest.raises(RuntimeError):
        complete_onboarding(fresh_user, 'Constructora Nueva')
    failing_storage.undo()

    state = complete_onboarding(fresh_user, 'Constructora Nueva')

    assert state['status'] == 'done'


@pytest.mark.django_db
@pytest.mark.escenario('A1-F01')
def test_onboarding_seeds_the_sample_with_a_working_comparison(fresh_user):
    """The wow: two analyzed versions + the auto comparison, without the user
    uploading anything."""
    state = complete_onboarding(fresh_user, 'Constructora Nueva')

    assert state['status'] == 'done'
    assert state['org_name'] == 'Constructora Nueva'
    assert '/compare/' in state['wow_link']
    from comparisons.models import Comparison

    comparison = Comparison.objects.get()
    assert comparison.status == 'done'
    assert comparison.summary['counts']['modified'] == 2


@pytest.mark.django_db
@pytest.mark.escenario('A1-F02')
@pytest.mark.escenario('A1-A03')
def test_onboarding_is_idempotent(fresh_user):
    first = complete_onboarding(fresh_user, 'Mi Org')
    second = complete_onboarding(fresh_user, 'Mi Org')

    assert first['project'] == second['project']
    from projects.models import Project

    assert Project.objects.filter(is_sample=True).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('A1-F03')
@pytest.mark.escenario('A1-P01')
@pytest.mark.escenario('A1-A02')
def test_state_endpoint_reports_pending_then_done(client_as, fresh_user):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(fresh_user)

    before = client.get('/api/me/onboarding/')
    assert before.data['status'] == 'pending'

    created = client.post('/api/me/onboarding/', {'org_name': 'Org Nueva'}, format='json')
    assert created.status_code == 201
    assert created.data['status'] == 'done'

    after = client.get('/api/me/onboarding/')
    assert after.data['status'] == 'done'
    assert after.data['wow_link'] == created.data['wow_link']


@pytest.mark.django_db
@pytest.mark.escenario('A1-P01')
def test_anonymous_cannot_touch_onboarding(client_as):
    assert client_as('anonymous').get('/api/me/onboarding/').status_code == 401
