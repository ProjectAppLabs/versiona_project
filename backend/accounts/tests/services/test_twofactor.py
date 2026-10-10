"""A3: TOTP lifecycle, the 2FA login challenge and session revocation."""

import pyotp
import pytest
from documents.services.version_service import DomainError
from rest_framework.test import APIClient

from accounts import twofactor


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email='segura@versiona.test', password='secreta123'
    )


@pytest.fixture
def enabled_user(user):
    setup = twofactor.setup(user)
    code = pyotp.TOTP(setup['secret']).now()
    backup_codes = twofactor.enable(user, code)
    user.refresh_from_db()
    return user, setup['secret'], backup_codes


@pytest.mark.django_db
@pytest.mark.escenario('A3-F01')
def test_setup_returns_secret_otpauth_and_qr(user):
    result = twofactor.setup(user)

    assert result['otpauth_url'].startswith('otpauth://totp/Versiona')
    assert result['qr'].startswith('data:image/png;base64,')
    user.refresh_from_db()
    assert user.totp_secret == result['secret']
    assert user.totp_enabled_at is None  # not yet active


@pytest.mark.django_db
@pytest.mark.escenario('A3-F02')
def test_enable_verifies_the_code_and_returns_backup_codes_once(enabled_user):
    user, secret, backup_codes = enabled_user

    assert user.totp_enabled_at is not None
    assert len(backup_codes) == twofactor.BACKUP_CODE_COUNT
    # Stored hashed, never plaintext:
    assert all(code not in user.totp_backup_codes for code in backup_codes)


@pytest.mark.django_db
@pytest.mark.escenario('A3-E01')
def test_enable_rejects_a_wrong_code(user):
    twofactor.setup(user)

    with pytest.raises(DomainError):
        twofactor.enable(user, '000000')


@pytest.mark.django_db
@pytest.mark.escenario('A3-F03')
def test_login_becomes_a_two_step_challenge(client_as, enabled_user):
    user, secret, _ = enabled_user
    client = APIClient()

    first = client.post('/api/sign_in/', {
        'email': user.email, 'password': 'secreta123',
    }, format='json')

    assert first.status_code == 202
    assert first.data['requires_2fa'] is True

    second = client.post('/api/sign_in/2fa/', {
        'challenge': first.data['challenge'],
        'code': pyotp.TOTP(secret).now(),
    }, format='json')

    assert second.status_code == 200
    assert 'access' in second.data
    assert 'refresh' in second.data


@pytest.mark.django_db
@pytest.mark.escenario('A3-E02')
def test_wrong_totp_code_keeps_the_door_closed(enabled_user):
    user, secret, _ = enabled_user
    client = APIClient()
    challenge = client.post('/api/sign_in/', {
        'email': user.email, 'password': 'secreta123',
    }, format='json').data['challenge']

    denied = client.post('/api/sign_in/2fa/', {
        'challenge': challenge, 'code': '000000',
    }, format='json')

    assert denied.status_code == 401


@pytest.mark.django_db
@pytest.mark.escenario('A3-A01')
def test_backup_code_works_exactly_once(enabled_user):
    user, _, backup_codes = enabled_user

    assert twofactor.verify_code(user, backup_codes[0]) is True
    user.refresh_from_db()
    assert twofactor.verify_code(user, backup_codes[0]) is False  # single use


@pytest.mark.django_db
@pytest.mark.escenario('A3-A02')
def test_disable_requires_a_valid_code(enabled_user):
    user, secret, _ = enabled_user

    with pytest.raises(DomainError):
        twofactor.disable(user, '000000')

    twofactor.disable(user, pyotp.TOTP(secret).now())
    user.refresh_from_db()
    assert user.totp_enabled_at is None
    assert user.totp_secret == ''


@pytest.mark.django_db
@pytest.mark.escenario('A3-F04')
def test_sessions_list_and_selective_revocation(user):
    from rest_framework_simplejwt.tokens import RefreshToken

    keep = RefreshToken.for_user(user)
    RefreshToken.for_user(user)
    RefreshToken.for_user(user)

    sessions = twofactor.list_sessions(user)
    assert len(sessions) == 3

    revoked = twofactor.revoke_other_sessions(user, str(keep))
    assert revoked == 2
    remaining = twofactor.list_sessions(user)
    assert len(remaining) == 1

    twofactor.revoke_session(user, remaining[0]['id'])
    assert twofactor.list_sessions(user) == []


@pytest.mark.django_db
@pytest.mark.escenario('A3-F05')
def test_security_endpoints_roundtrip(enabled_user):
    user, secret, _ = enabled_user
    client = APIClient()
    client.force_authenticate(user)

    security = client.get('/api/me/security/')
    assert security.data['totp_enabled'] is True
    assert security.data['backup_codes_left'] == twofactor.BACKUP_CODE_COUNT
    assert security.data['sso'] == 'DECISIÓN PENDIENTE'

    sessions = client.get('/api/me/sessions/')
    assert sessions.status_code == 200


@pytest.mark.django_db
def test_password_rotation_revokes_an_outstanding_totp_challenge(enabled_user):
    user, _, _ = enabled_user
    challenge = twofactor.issue_challenge(user)
    type(user).objects.filter(pk=user.pk).update(auth_version=1)
    with pytest.raises(DomainError):
        twofactor.resolve_challenge(challenge)


@pytest.mark.django_db
def test_email_recovery_revokes_a_totp_challenge(enabled_user):
    from accounts.models import PasswordCode
    user, _, _ = enabled_user
    challenge = twofactor.issue_challenge(user)
    code = PasswordCode.objects.create(user=user, code='123456')
    response = APIClient().post('/api/verify_passcode_and_reset_password/', {
        'email': user.email, 'code': code.code, 'new_password': 'Recovered-Valley!82',
    }, format='json')
    assert response.status_code == 200
    with pytest.raises(DomainError):
        twofactor.resolve_challenge(challenge)
