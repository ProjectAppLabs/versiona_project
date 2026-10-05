"""F1 trial: signup grant, lazy effective plan and console-override precedence."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from documents.services.version_service import DomainError
from freezegun import freeze_time
from orgs.services import ensure_personal_org

from billing.models import Subscription
from billing.services import (
    check_history_access,
    check_project_limit,
    effective_plan,
    start_trial,
    usage_report,
)


@pytest.fixture
def free_org(versiona_context):
    """Flip the shared context org to the free plan for this test."""
    org = versiona_context.org
    org.plan = 'free'
    org.save(update_fields=['plan'])
    return org


@pytest.mark.django_db
@pytest.mark.escenario('F1-T01')
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_signup_starts_a_pro_trial_on_the_new_personal_org(mock_captcha, api_client):
    """Pins the grant to the frozen signup instant AND the 14-day product promise.

    The literal (not settings.BILLING_TRIAL_DAYS) is what makes this catch
    something: recomputing with the same formula the SUT uses
    (billing/services.py:26) would move both sides together if
    BILLING_TRIAL_DAYS regressed to e.g. 13, staying green. The hand-verified
    14 (settings.py:444 default, the product's "14-day trial" promise) fails
    if either the clock base or the duration drifts — and correctly fails if
    the product promise itself is ever changed to something else.
    """
    frozen_now = timezone.now()
    with freeze_time(frozen_now):
        signup_response = api_client.post(
            reverse('sign_up'),
            {'email': 'nueva@versiona.test', 'password': 'NewPass!2026'},
            format='json',
        )

    assert signup_response.status_code == 201
    subscription = Subscription.objects.get(
        organization__memberships__user__email='nueva@versiona.test'
    )
    assert subscription.status == Subscription.Status.TRIALING
    assert subscription.plan_key == 'pro'
    assert subscription.trial_ends_at == frozen_now + timedelta(days=14)


@pytest.mark.django_db
@pytest.mark.escenario('F1-T01')
def test_ensure_personal_org_keeps_a_single_trial_on_relogin(django_user_model):
    """ensure_personal_org is idempotent: a relogin reuses the same org and never creates a second Subscription."""
    user = django_user_model.objects.create_user(
        email='relogin@versiona.test', password='secreta123'
    )

    first = ensure_personal_org(user)
    second = ensure_personal_org(user)

    assert first == second
    assert Subscription.objects.filter(organization=first).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('F1-T02')
def test_org_without_subscription_stays_on_its_stored_plan(free_org):
    """effective_plan returns the org's stored plan when there is no active trial."""
    assert effective_plan(free_org) == 'free'


@pytest.mark.django_db
@pytest.mark.escenario('F1-T02')
def test_effective_plan_is_pro_while_the_trial_runs(free_org):
    """effective_plan reads 'pro' for a free org with an active trial."""
    start_trial(free_org)

    assert effective_plan(free_org) == 'pro'


@pytest.mark.django_db
@pytest.mark.escenario('F1-T02')
def test_effective_plan_falls_back_to_free_after_expiry_without_beat(free_org):
    """effective_plan falls back to 'free' once the trial ends, even without the daily beat task running."""
    start_trial(free_org)

    with freeze_time(timezone.now() + timedelta(days=15)):
        assert effective_plan(free_org) == 'free'


@pytest.mark.django_db
@pytest.mark.escenario('F1-T03')
def test_console_override_pro_wins_over_an_expired_trial(free_org):
    """A console-set 'pro' plan wins over an already-expired trial."""
    subscription = start_trial(free_org)
    subscription.trial_ends_at = timezone.now() - timedelta(days=1)
    subscription.save(update_fields=['trial_ends_at'])
    free_org.plan = 'pro'
    free_org.save(update_fields=['plan'])

    assert effective_plan(free_org) == 'pro'


@pytest.mark.django_db
@pytest.mark.escenario('F1-T03')
def test_console_override_enterprise_wins_over_an_active_trial(free_org):
    """A console-set 'enterprise' plan wins over a still-active trial."""
    start_trial(free_org)
    free_org.plan = 'enterprise'
    free_org.save(update_fields=['plan'])

    assert effective_plan(free_org) == 'enterprise'


@pytest.mark.django_db
@pytest.mark.escenario('F1-T04')
def test_trial_lifts_the_free_project_limit(free_org):
    """Catches: a check_project_limit blind to an active trial.

    The free org is already at its 1-project ceiling, so it must be refused
    before start_trial and allowed after — asserting only the second half
    would also pass against a limit check that never raises at all.
    """
    with pytest.raises(DomainError) as exc:
        check_project_limit(free_org)
    assert exc.value.status_code == 402

    start_trial(free_org)

    assert check_project_limit(free_org) is None  # 1 active < pro's 20


@pytest.mark.django_db
@pytest.mark.escenario('F1-T04')
def test_expired_trial_restores_the_free_project_limit(free_org):
    """Once the trial expires, check_project_limit re-applies the free plan's 1-project ceiling."""
    start_trial(free_org)

    with freeze_time(timezone.now() + timedelta(days=15)):
        with pytest.raises(DomainError) as exc:
            check_project_limit(free_org)

    assert exc.value.status_code == 402


@pytest.mark.django_db
@pytest.mark.escenario('F1-T04')
def test_trial_lifts_the_member_limit_for_invitations(free_org, versiona_context):
    """Catches: create_invitation enforcing the seat cap without consulting the trial.

    The seeded org has 7 members, past free's 2 and under pro's 25, so the
    same invitation must be refused before the trial and issued after. The
    refused attempt persists nothing, so the second call starts from 7 too.
    """
    from orgs.invitations import create_invitation

    def invite():
        return create_invitation(
            versiona_context.project, versiona_context.users['admin'],
            email='octava@externa.co', role='viewer',
        )

    with pytest.raises(DomainError) as exc:
        invite()
    assert exc.value.status_code == 402

    start_trial(free_org)

    assert invite().email == 'octava@externa.co'


@pytest.mark.django_db
@pytest.mark.escenario('F1-T04')
def test_trial_unlocks_history_older_than_thirty_days(free_org, document_with_versions):
    """An active trial lifts the free plan's history lock for a version older than 30 days."""
    from documents.models import DocumentVersion

    document, versions = document_with_versions(n_versions=2)
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
        created_at=timezone.now() - timedelta(days=45)
    )
    def aged():
        # Re-fetched on purpose: check_history_access reaches the org through the
        # version's related objects, and an instance loaded before start_trial
        # keeps the pre-trial org cached.
        return DocumentVersion.objects.get(pk=versions[0].pk)

    with pytest.raises(DomainError) as exc:
        check_history_access(aged())
    assert exc.value.status_code == 402

    start_trial(free_org)

    assert check_history_access(aged()) is None


@pytest.mark.django_db
@pytest.mark.escenario('F2-T01')
def test_usage_report_carries_the_trial_block(free_org):
    """usage_report reports the effective 'pro' plan and the trial block (on_trial, days_left) while a trial is active."""
    start_trial(free_org)

    report = usage_report(free_org)

    assert report['plan'] == 'pro'
    assert report['effective_plan'] == 'pro'
    assert report['trial']['on_trial'] is True
    assert report['trial']['days_left'] == 14
    assert report['upgrade_available'] is True


@pytest.mark.django_db
@pytest.mark.escenario('F2-T01')
def test_usage_report_after_expiry_offers_the_upgrade(free_org):
    """usage_report falls back to the free plan and still offers the upgrade once the trial has expired."""
    start_trial(free_org)

    with freeze_time(timezone.now() + timedelta(days=15)):
        report = usage_report(free_org)

    assert report['plan'] == 'free'
    assert report['trial']['on_trial'] is False
    assert report['upgrade_available'] is True
