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
    result = _read_email_settings()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '5'


def test_smtp_accepts_a_positive_timeout_override():
    result = _read_email_settings('9')

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '9'


@pytest.mark.parametrize('value', ['0', '-1', 'infinite', 'nan'])
def test_smtp_rejects_an_invalid_timeout(value):
    result = _read_email_settings(value)

    assert result.returncode != 0
    assert 'DJANGO_EMAIL_TIMEOUT' in result.stderr


def test_smtp_passes_the_timeout_to_its_socket(settings, monkeypatch):
    settings.EMAIL_TIMEOUT = 5
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    smtp = MagicMock()
    monkeypatch.setattr('django.core.mail.backends.smtp.smtplib.SMTP', smtp)

    connection = get_connection('django.core.mail.backends.smtp.EmailBackend')
    connection.open()
    connection.close()

    assert smtp.call_args.kwargs['timeout'] == 5


@pytest.mark.django_db
def test_smtp_timeout_preserves_the_in_app_notification(versiona_context, settings, monkeypatch):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    settings.EMAIL_TIMEOUT = 5
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    monkeypatch.setattr(
        'django.core.mail.backends.smtp.smtplib.SMTP', MagicMock(side_effect=TimeoutError('smtp stalled')),
    )

    notification = notify(
        user=versiona_context.users['reviewer'], event_key='seal.invalidated',
        org=versiona_context.org, title='Volver a revisar', body='Cambió una sección.',
    )

    assert Notification.objects.filter(pk=notification.pk, event_key='seal.invalidated').exists()
