import smtplib

import pytest
from django.contrib.auth import get_user_model

from accounts.utils import auth_utils


def _refusing_send_mail(*_args, **_kwargs):
    """SMTP rejection whose message names the refused recipient, as smtplib does."""
    raise smtplib.SMTPRecipientsRefused(
        {'resetfail@example.com': (550, b'mailbox unavailable')}
    )


def _auth_email_warnings(caplog):
    return [
        record.getMessage() for record in caplog.records
        if record.name == 'accounts.utils.auth_utils'
    ]


@pytest.mark.django_db
def test_generate_auth_tokens_contains_user_payload():
    User = get_user_model()
    user = User.objects.create_user(email='tokens@example.com', password='pass1234')

    tokens = auth_utils.generate_auth_tokens(user)

    assert tokens['user']['email'] == 'tokens@example.com'
    assert tokens['user']['id'] == user.id
    assert tokens['refresh']
    assert tokens['access']
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
    assert AccessToken(tokens['access'])['auth_version'] == 0
    assert RefreshToken(tokens['refresh'])['auth_version'] == 0


@pytest.mark.django_db
def test_send_password_reset_code_success(monkeypatch):
    User = get_user_model()
    user = User.objects.create_user(email='reset@example.com', password='pass1234', first_name='Reset')
    sent = {}

    def fake_send_mail(subject, message, from_email, recipient_list, fail_silently):
        sent['subject'] = subject
        sent['recipients'] = recipient_list
        return 1

    monkeypatch.setattr(auth_utils, 'send_mail', fake_send_mail)

    assert auth_utils.send_password_reset_code(user, '123456') is True
    assert sent['recipients'] == [user.email]


@pytest.mark.django_db
def test_send_password_reset_code_failure(monkeypatch):
    User = get_user_model()
    user = User.objects.create_user(email='resetfail@example.com', password='pass1234', first_name='Reset')

    def fake_send_mail(*_args, **_kwargs):
        raise RuntimeError('send failed')

    monkeypatch.setattr(auth_utils, 'send_mail', fake_send_mail)

    assert auth_utils.send_password_reset_code(user, '123456') is False


@pytest.mark.django_db
def test_send_verification_code_success(monkeypatch):
    sent = {}

    def fake_send_mail(subject, message, from_email, recipient_list, fail_silently):
        sent['subject'] = subject
        sent['recipients'] = recipient_list
        return 1

    monkeypatch.setattr(auth_utils, 'send_mail', fake_send_mail)

    assert auth_utils.send_verification_code('verify@example.com', '654321') is True
    assert sent['recipients'] == ['verify@example.com']


@pytest.mark.django_db
def test_send_verification_code_failure(monkeypatch):
    def fake_send_mail(*_args, **_kwargs):
        raise RuntimeError('send failed')

    monkeypatch.setattr(auth_utils, 'send_mail', fake_send_mail)

    assert auth_utils.send_verification_code('verify@example.com', '654321') is False


@pytest.mark.django_db
def test_password_reset_failure_logs_the_error_class(monkeypatch, caplog):
    """Catches: a reset email failure that never reaches the application log."""
    User = get_user_model()
    user = User.objects.create_user(email='resetfail@example.com', password='pass1234')
    monkeypatch.setattr(auth_utils, 'send_mail', _refusing_send_mail)

    auth_utils.send_password_reset_code(user, '123456')

    assert _auth_email_warnings(caplog) == [
        'Password reset email not delivered: phase=password_reset_email '
        'error_class=SMTPRecipientsRefused'
    ]


@pytest.mark.django_db
def test_password_reset_failure_keeps_the_address_out_of_the_output(monkeypatch, caplog, capsys):
    """Catches: the refused recipient address printed to stdout, hence the service journal."""
    User = get_user_model()
    user = User.objects.create_user(email='resetfail@example.com', password='pass1234')
    monkeypatch.setattr(auth_utils, 'send_mail', _refusing_send_mail)

    auth_utils.send_password_reset_code(user, '123456')

    assert 'resetfail@example.com' not in capsys.readouterr().out + caplog.text


def test_verification_failure_logs_the_error_class(monkeypatch, caplog):
    """Catches: a verification email failure that never reaches the application log."""
    monkeypatch.setattr(auth_utils, 'send_mail', _refusing_send_mail)

    auth_utils.send_verification_code('verify@example.com', '654321')

    assert _auth_email_warnings(caplog) == [
        'Verification email not delivered: phase=verification_email '
        'error_class=SMTPRecipientsRefused'
    ]
