"""SMTP configuration imposes a finite wait without breaking in-app delivery."""

import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from django.core.mail import get_connection

from notifications.models import Notification
from notifications.services import notify


def _read_email_settings(value=None):
    environment = {key: value for key, value in os.environ.items() if key != 'DJANGO_EMAIL_TIMEOUT'}
    environment['DJANGO_ENV'] = 'test'
    if value is not None:
        environment['DJANGO_EMAIL_TIMEOUT'] = value
    # Block the dotenv boundary: never read the linked deployment .env in this child.
    code = (
        'import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; '
        'from versiona_project import settings; print(settings.EMAIL_TIMEOUT)'
    )
    return subprocess.run(
        [sys.executable, '-c', code], env=environment, capture_output=True, text=True, timeout=10,
    )


def test_smtp_default_timeout_is_five_seconds():
    """Smtp default timeout is five seconds."""
    result = _read_email_settings()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '5'


def test_smtp_accepts_a_positive_timeout_override():
    """Smtp accepts a positive timeout override."""
    result = _read_email_settings('9')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '9'


@pytest.mark.parametrize('value', ['0', '-1', 'infinite', 'nan'])
def test_smtp_rejects_an_invalid_timeout(value):
    """Smtp rejects an invalid timeout."""
    result = _read_email_settings(value)

    assert result.returncode != 0
    assert 'DJANGO_EMAIL_TIMEOUT' in result.stderr


def test_smtp_passes_the_timeout_to_its_socket(settings, monkeypatch):
    """Smtp passes the timeout to its socket."""
    settings.EMAIL_TIMEOUT = 5
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    smtp = MagicMock()
    monkeypatch.setattr('django.core.mail.backends.smtp.smtplib.SMTP', smtp)

    connection = get_connection('django.core.mail.backends.smtp.EmailBackend')
    connection.open()
    connection.close()

    smtp.assert_called_once()
    assert smtp.call_args.kwargs['timeout'] == 5


@pytest.mark.django_db
def test_smtp_timeout_preserves_the_in_app_notification(versiona_context, settings, monkeypatch):
    """Smtp timeout preserves the in app notification."""
    settings.EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    settings.EMAIL_TIMEOUT = 5
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    smtp = MagicMock(side_effect=TimeoutError('smtp stalled'))
    monkeypatch.setattr('django.core.mail.backends.smtp.smtplib.SMTP', smtp)

    notification = notify(
        user=versiona_context.users['reviewer'], event_key='seal.invalidated',
        org=versiona_context.org, title='Volver a revisar', body='Cambió una sección.',
    )

    assert Notification.objects.filter(pk=notification.pk, event_key='seal.invalidated').exists()
    smtp.assert_called_once()


@pytest.fixture
def stalled_smtp(settings, monkeypatch):
    """SMTP boundary whose connection times out, like an unreachable relay."""
    settings.EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    settings.EMAIL_TIMEOUT = 5
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    monkeypatch.setattr(
        'django.core.mail.backends.smtp.smtplib.SMTP',
        MagicMock(side_effect=TimeoutError('smtp stalled')),
    )


def _invalidation_notice(context):
    return notify(
        user=context.users['reviewer'], event_key='seal.invalidated', org=context.org,
        title='Volver a revisar', body='Cambió una sección.', link='/projects/demo',
    )


@pytest.mark.django_db
def test_undelivered_email_leaves_the_send_time_empty(versiona_context, stalled_smtp):
    """Catches: recording an email as sent when the SMTP relay never accepted it."""
    notification = _invalidation_notice(versiona_context)

    notification.refresh_from_db()
    assert notification.email_sent_at is None


@pytest.mark.django_db
def test_undelivered_email_logs_a_sanitized_warning(versiona_context, stalled_smtp, caplog):
    """Catches: an SMTP outage that leaves no trace, or a trace with the recipient or link."""
    _invalidation_notice(versiona_context)

    assert [
        record.getMessage() for record in caplog.records
        if record.name == 'notifications.services'
    ] == [
        'Notification email not delivered: phase=notification_email '
        'event=seal.invalidated error_class=TimeoutError'
    ]


@pytest.mark.django_db
def test_delivered_email_records_its_send_time(versiona_context, mailoutbox):
    """Catches: never recording the send time once the relay accepted the email."""
    notification = _invalidation_notice(versiona_context)

    notification.refresh_from_db()
    assert notification.email_sent_at is not None
