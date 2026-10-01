"""A3 security endpoints: 2FA lifecycle + session revocation through the API."""

import pyotp
import pytest
from django.core import signing
from freezegun import freeze_time
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import twofactor


@pytest.fixture
def user(django_user_model):
    """Create the account used by security endpoint tests."""
    return django_user_model.objects.create_user(
        email='segura@versiona.test', password='secreta123'
    )


@pytest.fixture
def auth_client(user):
    """Return an API client authenticated as the security test user."""
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def enabled_user(user):
    """Enroll the security test user in TOTP and return its recovery data."""
    setup = twofactor.setup(user)
    code = pyotp.TOTP(setup['secret']).now()
    backup_codes = twofactor.enable(user, code)
    user.refresh_from_db()
    return user, setup['secret'], backup_codes


@pytest.mark.django_db
@pytest.mark.escenario('A3-C01')
def test_setup_endpoint_returns_enrolment_material(auth_client, user):
    """Return a QR payload and persist the TOTP secret during setup."""
    response = auth_client.post('/api/me/2fa/setup/')

    assert response.status_code == 200
    assert response.data['qr'].startswith('data:image/png;base64,')
    user.refresh_from_db()
    assert user.totp_secret == response.data['secret']


@pytest.mark.django_db
@pytest.mark.escenario('A3-C02')
def test_setup_endpoint_conflicts_when_2fa_already_active(auth_client, enabled_user):
    """Reject a second TOTP enrolment while two-factor auth is active."""
    response = auth_client.post('/api/me/2fa/setup/')

    assert response.status_code == 409
    assert response.data['error'] == 'El 2FA ya está activo. Desactívalo antes de re-enrolar.'


@pytest.mark.django_db
@pytest.mark.escenario('A3-C03')
def test_enable_endpoint_returns_backup_codes(auth_client, user):
    """Return the configured number of backup codes after valid TOTP setup."""
    secret = twofactor.setup(user)['secret']

    response = auth_client.post(
        '/api/me/2fa/enable/', {'code': pyotp.TOTP(secret).now()}, format='json'
    )

    assert response.status_code == 201
    assert len(response.data['backup_codes']) == twofactor.BACKUP_CODE_COUNT


@pytest.mark.django_db
@pytest.mark.escenario('A3-C04')
def test_enable_endpoint_rejects_a_wrong_code(auth_client, user):
    """Reject TOTP activation when the submitted code is incorrect."""
    twofactor.setup(user)

    response = auth_client.post('/api/me/2fa/enable/', {'code': '000000'}, format='json')

    assert response.status_code == 400
    assert response.data['error'] == 'Código incorrecto. Verifica la hora de tu dispositivo.'


@pytest.mark.django_db
@pytest.mark.escenario('A3-C05')
def test_disable_endpoint_turns_2fa_off(auth_client, enabled_user):
    """Clear the TOTP activation timestamp after a valid disable request."""
    user, secret, _ = enabled_user

    response = auth_client.post(
        '/api/me/2fa/disable/', {'code': pyotp.TOTP(secret).now()}, format='json'
    )

    assert response.status_code == 200
    assert response.data == {'totp_enabled': False}
    user.refresh_from_db()
    assert user.totp_enabled_at is None


@pytest.mark.django_db
@pytest.mark.escenario('A3-C06')
def test_disable_endpoint_rejects_a_wrong_code(auth_client, enabled_user):
    """Keep two-factor auth active when the disable code is incorrect."""
    response = auth_client.post('/api/me/2fa/disable/', {'code': '000000'}, format='json')

    assert response.status_code == 400
    assert response.data['error'] == 'Código incorrecto.'


@pytest.mark.django_db
@pytest.mark.escenario('A3-C07')
def test_session_revoke_endpoint_blacklists_the_session(auth_client, user):
    """Remove the selected refresh-token session from the active list."""
    RefreshToken.for_user(user)
    session_id = twofactor.list_sessions(user)[0]['id']

    response = auth_client.post(f'/api/me/sessions/{session_id}/revoke/')

    assert response.status_code == 200
    assert response.data == {'revoked': session_id}
    assert twofactor.list_sessions(user) == []


@pytest.mark.django_db
@pytest.mark.escenario('A3-C08')
@pytest.mark.escenario('A3-P01')
def test_session_revoke_endpoint_returns_404_for_unknown_session(auth_client):
    """Return not found when revoking an unknown session identifier."""
    response = auth_client.post('/api/me/sessions/999999/revoke/')

    assert response.status_code == 404
    assert response.data['error'] == 'Sesión no encontrada.'


@pytest.mark.django_db
@pytest.mark.escenario('A3-C09')
def test_revoke_others_endpoint_keeps_only_the_given_refresh(auth_client, user):
    """Revoke every session except the refresh token supplied by the caller."""
    keep = RefreshToken.for_user(user)
    RefreshToken.for_user(user)
    RefreshToken.for_user(user)

    response = auth_client.post(
        '/api/me/sessions/revoke_others/', {'refresh': str(keep)}, format='json'
    )

    assert response.status_code == 200
    assert response.data == {'revoked': 2}
    assert len(twofactor.list_sessions(user)) == 1


@pytest.mark.django_db
@pytest.mark.escenario('A3-L01')
def test_revoke_others_without_a_refresh_closes_every_session(auth_client, user):
    """Close every active session when no refresh token is retained."""
    RefreshToken.for_user(user)
    RefreshToken.for_user(user)
    RefreshToken.for_user(user)

    response = auth_client.post('/api/me/sessions/revoke_others/', {}, format='json')

    assert response.data == {'revoked': 3}
    assert twofactor.list_sessions(user) == []


@pytest.mark.django_db
@pytest.mark.escenario('A3-L01')
def test_revoke_others_keeps_the_current_refresh_usable(auth_client, user, api_client):
    """Keep the retained refresh token usable after revoking other sessions."""
    keep = RefreshToken.for_user(user)
    RefreshToken.for_user(user)
    auth_client.post(
        '/api/me/sessions/revoke_others/', {'refresh': str(keep)}, format='json'
    )

    refreshed = api_client.post(
        '/api/token/refresh/', {'refresh': str(keep)}, format='json'
    )

    assert refreshed.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    'challenge',
    [
        '',
        'not-a-signed-challenge',
        signing.dumps([], salt=twofactor.CHALLENGE_SALT),
        signing.dumps({'user': '7'}, salt=twofactor.CHALLENGE_SALT),
        signing.dumps({'user': True}, salt=twofactor.CHALLENGE_SALT),
    ],
    ids=['empty', 'bad-signature', 'signed-list', 'string-user-id', 'bool-user-id'],
)
def test_sign_in_2fa_rejects_malformed_challenges(challenge, api_client):
    """Fails if malformed signed challenges escape the generic 401 admission error."""
    outstanding_before = OutstandingToken.objects.count()

    response = api_client.post(
        '/api/sign_in/2fa/', {'challenge': challenge, 'code': '000000'}, format='json'
    )

    assert response.status_code == 401
    assert response.data == {'error': 'Desafío inválido o vencido.'}
    assert OutstandingToken.objects.count() == outstanding_before


@pytest.mark.django_db
def test_sign_in_2fa_rejects_an_expired_challenge(enabled_user, api_client):
    """Fails if a stale first-factor proof can still mint a TOTP session."""
    user, _secret, _backup_codes = enabled_user
    with freeze_time('2026-10-01 10:00:00'):
        challenge = twofactor.issue_challenge(user)
    outstanding_before = OutstandingToken.objects.count()

    with freeze_time('2026-10-01 10:06:00'):
        response = api_client.post(
            '/api/sign_in/2fa/', {'challenge': challenge, 'code': '000000'}, format='json'
        )

    assert response.status_code == 401
    assert response.data == {'error': 'Desafío inválido o vencido.'}
    assert OutstandingToken.objects.count() == outstanding_before


@pytest.mark.django_db
def test_sign_in_2fa_rejects_a_deleted_challenge_user(enabled_user, api_client):
    """Fails if a challenge can authenticate a user removed after the first factor."""
    user, _secret, _backup_codes = enabled_user
    challenge = twofactor.issue_challenge(user)
    user.delete()
    outstanding_before = OutstandingToken.objects.count()

    response = api_client.post(
        '/api/sign_in/2fa/', {'challenge': challenge, 'code': '000000'}, format='json'
    )

    assert response.status_code == 401
    assert response.data == {'error': 'Desafío inválido o vencido.'}
    assert OutstandingToken.objects.count() == outstanding_before


@pytest.mark.django_db
def test_sign_in_2fa_rejects_an_inactive_challenge_user(enabled_user, api_client):
    """Fails if account deactivation after the first factor still grants a session."""
    user, _secret, _backup_codes = enabled_user
    challenge = twofactor.issue_challenge(user)
    user.is_active = False
    user.save(update_fields=['is_active'])
    outstanding_before = OutstandingToken.objects.count()

    response = api_client.post(
        '/api/sign_in/2fa/', {'challenge': challenge, 'code': '000000'}, format='json'
    )

    assert response.status_code == 401
    assert response.data == {'error': 'Desafío inválido o vencido.'}
    assert OutstandingToken.objects.count() == outstanding_before


@pytest.mark.django_db
def test_sign_in_2fa_rejects_a_user_with_disabled_totp_after_challenge(enabled_user, api_client):
    """Fails if disabling TOTP after a challenge leaves a usable second-factor grant."""
    user, _secret, _backup_codes = enabled_user
    challenge = twofactor.issue_challenge(user)
    user.totp_enabled_at = None
    user.save(update_fields=['totp_enabled_at'])
    outstanding_before = OutstandingToken.objects.count()

    response = api_client.post(
        '/api/sign_in/2fa/', {'challenge': challenge, 'code': '000000'}, format='json'
    )

    assert response.status_code == 401
    assert response.data == {'error': 'Desafío inválido o vencido.'}
    assert OutstandingToken.objects.count() == outstanding_before
