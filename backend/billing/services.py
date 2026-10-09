"""F1 limit enforcement + F2 usage (I13, DP-04: lock, never delete)."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from documents.queries import is_current_version
from documents.services.version_service import DomainError

from .models import TRIAL_PLAN_KEY, WARNING_THRESHOLD, Subscription, plan_limits

UPGRADE_CTA = (
    'Tu plan {label} llegó a su límite de {what}. Mejora tu plan para seguir '
    'creciendo — el pago en línea llega pronto; escríbenos mientras tanto.'
)


def start_trial(org) -> Subscription:
    """Grant the signup trial (F1). Idempotent per organization."""
    subscription, _ = Subscription.objects.get_or_create(
        organization=org,
        defaults={
            'plan_key': TRIAL_PLAN_KEY,
            'status': Subscription.Status.TRIALING,
            'trial_ends_at': timezone.now()
            + timedelta(days=settings.BILLING_TRIAL_DAYS),
        },
    )
    return subscription


def _active_trial(org):
    subscription = getattr(org, 'subscription', None)
    if (
        subscription
        and subscription.status == Subscription.Status.TRIALING
        and subscription.trial_ends_at > timezone.now()
    ):
        return subscription
    return None


def effective_plan(org) -> str:
    """Console override (`Organization.plan` != free) > active trial > free.

    Lazy by design: trial expiry takes effect at read time even if the daily
    beat task has not run yet.
    """
    if org.plan != 'free':
        return org.plan
    trial = _active_trial(org)
    return trial.plan_key if trial else 'free'


def _usage(org) -> dict:
    from orgs.models import OrganizationMembership

    plan_key = effective_plan(org)
    limits = plan_limits(plan_key)
    active_projects = org.projects.filter(status='active').count()
    members = OrganizationMembership.objects.filter(organization=org).count()
    return {
        'plan': plan_key,
        'plan_label': limits['label'],
        'limits': {
            'max_active_projects': limits['max_active_projects'],
            'max_members': limits['max_members'],
            'history_days': limits['history_days'],
        },
        'usage': {'active_projects': active_projects, 'members': members},
    }


def usage_report(org) -> dict:
    """F2: usage vs limits with preventive warnings at 80%."""
    report = _usage(org)
    warnings = []
    for key, used in (
        ('max_active_projects', report['usage']['active_projects']),
        ('max_members', report['usage']['members']),
    ):
        limit = report['limits'][key]
        if limit and used / limit >= WARNING_THRESHOLD:
            warnings.append({
                'limit': key,
                'used': used,
                'max': limit,
                'at_capacity': used >= limit,
            })
    report['warnings'] = warnings
    trial = _active_trial(org)
    report['effective_plan'] = report['plan']
    report['trial'] = {
        'on_trial': trial is not None,
        'trial_ends_at': trial.trial_ends_at if trial else None,
        'days_left': (
            (trial.trial_ends_at.date() - timezone.now().date()).days
            if trial else None
        ),
    }
    report['upgrade_available'] = report['plan'] == 'free' or trial is not None
    return report


def check_project_limit(org):
    """Raised BEFORE creating a project (F1-L01)."""
    report = _usage(org)
    limit = report['limits']['max_active_projects']
    if limit and report['usage']['active_projects'] >= limit:
        raise DomainError(
            UPGRADE_CTA.format(label=report['plan_label'],
                               what=f'{limit} proyecto(s) activo(s)'),
            402,
        )


def check_member_limit(org):
    """Raised BEFORE inviting / accepting a NEW member (F1-L02)."""
    report = _usage(org)
    limit = report['limits']['max_members']
    if limit and report['usage']['members'] >= limit:
        raise DomainError(
            UPGRADE_CTA.format(label=report['plan_label'],
                               what=f'{limit} miembro(s)'),
            402,
        )


def check_history_access(version):
    """DP-04 / C3-L02: on the free plan, versions older than the window are
    LOCKED (never deleted) — except each document's current version."""
    org = version.document.project.organization
    limits = plan_limits(effective_plan(org))
    window = limits['history_days']
    if window is None:
        return
    if is_current_version(version):
        return
    age = timezone.now() - version.created_at
    if age.days >= window:
        raise DomainError(
            f'El historial de más de {window} días está bloqueado en el plan '
            f'{limits["label"]} (la versión sigue guardada, nada se borra). '
            'Mejora tu plan para acceder.',
            402,
        )
