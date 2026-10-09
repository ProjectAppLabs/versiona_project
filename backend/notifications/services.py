"""Notification delivery (kit 5): in-app always + email per preference,
rendered per-recipient language through the bilingual template registry."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import NOTIFICATION_CATALOG, Notification, NotificationPreference
from .templates import render

logger = logging.getLogger(__name__)


def _wants(user, event_key: str, channel: str) -> bool:
    catalog = NOTIFICATION_CATALOG.get(event_key, {})
    if channel == 'in_app' and catalog.get('mandatory_in_app'):
        return True
    pref = NotificationPreference.objects.filter(
        user=user, event_key=event_key, channel=channel
    ).first()
    if pref is not None:
        return pref.enabled
    return bool(catalog.get(f'default_{channel}', False))


def notify(*, user, event_key: str, org, project=None, context: dict | None = None,
           title: str = '', body: str = '', link: str = '',
           payload: dict | None = None) -> Notification | None:
    """Returns the in-app notification (None when the user opted out and the
    event is not mandatory). Copy comes from the bilingual registry rendered
    with `context` in the RECIPIENT's language; explicit title/body override
    it. S6 lives here: `seal.preserved` defaults to OFF on both channels."""
    wants_in_app = _wants(user, event_key, 'in_app')
    wants_email = _wants(user, event_key, 'email')
    if not wants_in_app and not wants_email:
        return None

    if not title:
        language = getattr(user, 'language', 'es') or 'es'
        title, body = render(event_key, language, context)

    notification = None
    if wants_in_app:
        notification = Notification.objects.create(
            user=user,
            org_id_ref=org.pk,
            project_id_ref=project.pk if project else None,
            event_key=event_key,
            title=title,
            body=body,
            link=link,
            payload=payload or {},
        )

    if wants_email and _send_email(user, event_key, title, body, link) and notification:
        notification.email_sent_at = timezone.now()
        notification.save(update_fields=['email_sent_at', 'updated_at'])

    return notification


def _send_email(user, event_key: str, title: str, body: str, link: str) -> bool:
    """True only when the backend accepted the message. Email must never break
    the domain transaction, yet a refused or unreachable relay stays visible."""
    try:
        delivered = send_mail(
            subject=title,
            message=f'{body}\n\n{settings.FRONTEND_URL}{link}' if link else body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as exc:
        # Event and error class only: never the recipient, the copy or the link.
        logger.warning(
            'Notification email not delivered: phase=notification_email '
            'event=%s error_class=%s',
            event_key, type(exc).__name__,
            extra={
                'phase': 'notification_email', 'event_key': event_key,
                'error_class': type(exc).__name__,
            },
        )
        return False
    return bool(delivered)
