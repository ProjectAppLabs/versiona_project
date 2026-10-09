"""F1 limits (I13, DP-04: lock never delete) + F2 usage warnings."""

from datetime import timedelta

import pytest
from django.utils import timezone
from documents.services.version_service import DomainError
from freezegun import freeze_time

from billing.models import plan_limits
from billing.services import (
    check_history_access,
    check_project_limit,
    usage_report,
)


@pytest.fixture(autouse=True)
def _free_plan(versiona_context):
    """Flip the shared context org to the free plan.

    The shared context org defaults to `pro` (it exercises every flow); the
    limit tests are exactly about `free`, so they set it explicitly.
    """
    org = versiona_context.org
    org.plan = 'free'
    org.save(update_fields=['plan'])
    return org


@pytest.mark.django_db
@pytest.mark.escenario('F1-L01')
@pytest.mark.escenario('B1-L01')
def test_free_plan_allows_one_active_project(versiona_context):
    """A second active project on the free plan is rejected with the upgrade CTA.

    The seeded org already has Torre Central active ⇒ creating another one
    hits the 402 with the informative message.
    """
    org = versiona_context.org

    with pytest.raises(DomainError) as exc:
        check_project_limit(org)

    assert exc.value.status_code == 402
    assert 'Mejora tu plan' in str(exc.value)


@pytest.mark.django_db
@pytest.mark.escenario('F1-L01')
def test_pro_plan_lifts_the_project_limit(versiona_context):
    """Catches: a check_project_limit that ignores the plan.

    Asserting only that pro does not raise cannot catch it — a check that did
    nothing at all would pass. The contrast on the SAME org is what pins the
    plan as the cause.
    """
    org = versiona_context.org

    with pytest.raises(DomainError) as exc:
        check_project_limit(org)
    assert exc.value.status_code == 402

    org.plan = 'pro'
    org.save(update_fields=['plan'])

    assert check_project_limit(org) is None


@pytest.mark.django_db
@pytest.mark.escenario('F1-L02')
@pytest.mark.escenario('A2-L01')
def test_member_limit_blocks_new_invitations(versiona_context):
    """A new invitation is blocked once the free plan's seat cap is hit.

    The seeded org has 7 members — way past free's 2 ⇒ inviting is blocked
    (existing members are NEVER removed: DP-04).
    """
    from orgs.invitations import create_invitation

    with pytest.raises(DomainError) as exc:
        create_invitation(
            versiona_context.project, versiona_context.users['admin'],
            email='octava@externa.co', role='viewer',
        )

    assert exc.value.status_code == 402


@pytest.mark.django_db
@pytest.mark.escenario('C3-L02')
@pytest.mark.escenario('F1-L03')
def test_old_history_is_locked_not_deleted_on_free(versiona_context, document_with_versions):
    """Backdates to EXACTLY the free window (30 days), not comfortably past it.

    An off-by-one loosening of `age.days >= window` to `age.days > window`
    (billing/services.py:140) stops blocking right at this edge (30 > 30 is
    False) and would slip through undetected — a 45 or 31-day backdate still
    raises under either operator and would miss the regression.
    """
    document, versions = document_with_versions(n_versions=2)
    from documents.models import DocumentVersion

    window = plan_limits('free')['history_days']
    frozen_now = timezone.now()
    with freeze_time(frozen_now):
        DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
            created_at=frozen_now - timedelta(days=window)
        )
        old = DocumentVersion.objects.get(pk=versions[0].pk)

        with pytest.raises(DomainError) as exc:
            check_history_access(old)

        assert exc.value.status_code == 402
        assert 'nada se borra' in str(exc.value)


@pytest.mark.django_db
@pytest.mark.escenario('C3-L02')
@pytest.mark.escenario('F1-L03')
def test_latest_version_is_always_accessible_regardless_of_age_on_free(
    versiona_context, document_with_versions
):
    """The current-version short-circuit skips the age check entirely, on free.

    Catches a regression that removes or breaks the current-version
    short-circuit of check_history_access — without it, an old-but-current
    version would wrongly get locked out.
    """
    document, versions = document_with_versions(n_versions=2)
    from documents.models import DocumentVersion

    frozen_now = timezone.now()
    with freeze_time(frozen_now):
        DocumentVersion.all_objects.filter(pk=versions[1].pk).update(
            created_at=frozen_now - timedelta(days=45)
        )
        result = check_history_access(DocumentVersion.objects.get(pk=versions[1].pk))

    assert result is None


@pytest.mark.django_db
@pytest.mark.escenario('C3-L02')
@pytest.mark.escenario('F1-L03')
def test_current_version_stays_accessible_after_trashing_a_newer_draft(
    versiona_context, document_with_versions
):
    """Catches: the free-plan exemption following the allocation counter, so
    trashing the newest draft locked the document's current version (DP-04)."""
    from documents.models import DocumentVersion
    from documents.services import trash_service

    document, versions = document_with_versions(n_versions=2)
    trash_service.trash_version(versions[1], versiona_context.users['editor'])

    frozen_now = timezone.now()
    with freeze_time(frozen_now):
        DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
            created_at=frozen_now - timedelta(days=45)
        )
        result = check_history_access(DocumentVersion.objects.get(pk=versions[0].pk))

    assert result is None


@pytest.mark.django_db
@pytest.mark.escenario('C3-L02')
def test_pro_plan_unlocks_history(versiona_context, document_with_versions):
    """Catches: a check_history_access that never consults the plan.

    400 days is far past free's 30-day window, so the same version must be
    refused on free and allowed on pro — the pair is what proves the window
    is plan-driven.
    """
    document, versions = document_with_versions(n_versions=2)
    org = versiona_context.org
    from documents.models import DocumentVersion

    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
        created_at=timezone.now() - timedelta(days=400)
    )
    def aged():
        # Re-fetched on purpose: check_history_access reaches the org through the
        # version's related objects, and an instance loaded before the plan change
        # keeps the stale plan cached — it would still read `free`.
        return DocumentVersion.objects.get(pk=versions[0].pk)

    with pytest.raises(DomainError) as exc:
        check_history_access(aged())
    assert exc.value.status_code == 402

    org.plan = 'pro'
    org.save(update_fields=['plan'])

    assert check_history_access(aged()) is None


@pytest.mark.django_db
@pytest.mark.escenario('F2-F01')
@pytest.mark.escenario('F2-L01')
def test_usage_report_warns_at_capacity(versiona_context):
    """usage_report flags active_projects and max_members past the 80% threshold, with max_members already at capacity."""
    report = usage_report(versiona_context.org)

    assert report['plan'] == 'free'
    assert report['usage']['active_projects'] == 1
    assert report['upgrade_available'] is True
    limits_flagged = {warning['limit'] for warning in report['warnings']}
    assert 'max_active_projects' in limits_flagged  # 1/1 = at capacity
    assert 'max_members' in limits_flagged  # 7/2
    at_capacity = {w['limit']: w['at_capacity'] for w in report['warnings']}
    assert at_capacity['max_members'] is True


@pytest.mark.django_db
@pytest.mark.escenario('F1-F01')
@pytest.mark.escenario('B1-L01')
def test_create_project_endpoint_returns_402_with_upgrade_flag(client_as, versiona_context):
    """The create-project endpoint returns 402 with an upgrade flag once the free plan's project limit is hit."""
    response = client_as('owner').post(
        f'/api/orgs/{versiona_context.org.public_id}/projects/',
        {'name': 'Segundo proyecto'},
        format='json',
    )

    assert response.status_code == 402
    assert response.data['upgrade'] is True


@pytest.mark.django_db
@pytest.mark.escenario('F2-F02')
@pytest.mark.escenario('F2-P01')
def test_usage_endpoint_visible_to_members_only(client_as, versiona_context):
    """The usage endpoint is visible to org members but returns 404 for a non-member."""
    url = f'/api/orgs/{versiona_context.org.public_id}/usage/'

    member = client_as('viewer').get(url)
    outsider = client_as('non_member').get(url)

    assert member.status_code == 200
    assert member.data['limits']['max_members'] == 2
    assert outsider.status_code == 404
