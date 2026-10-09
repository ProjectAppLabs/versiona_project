"""Authentication endpoint behavior and Google/TOTP admission tests."""

import secrets
from datetime import timedelta
from unittest.mock import Mock, patch

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from orgs.models import Organization, OrganizationMembership
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from accounts import twofactor
from accounts.models import PasswordCode
from accounts.views import auth as auth_views

_UNSET = object()


class DummyResponse:
    """Represent the tokeninfo response surface used by Google login tests."""

    def __init__(self, status_code=200, payload=_UNSET, text='', json_error=None):
        """Store a configurable HTTP status, payload, and JSON failure."""
        self.status_code = status_code
        self._payload = {} if payload is _UNSET else payload
        self.text = text
        self._json_error = json_error

    def json(self):
        """Return the configured payload or raise the configured JSON error."""
        if self._json_error is not None:
            raise self._json_error
        return self._payload


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_up_requires_email_and_password(mock_captcha, api_client):
    """Reject sign-up requests that omit the required credentials."""
    response = api_client.post(reverse('sign_up'), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Email and password are required'


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_up_rejects_existing_email(mock_captcha, api_client):
    """Reject sign-up when the submitted email already belongs to a user."""
    User = get_user_model()
    User.objects.create_user(email='existing@example.com', password='pass1234')

    response = api_client.post(
        reverse('sign_up'),
        {'email': 'existing@example.com', 'password': 'pass1234'},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'User with this email already exists'


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_up_creates_user(mock_captcha, api_client):
    """Verifies sign-up creates a new user record and returns an access token on success."""
    response = api_client.post(
        reverse('sign_up'),
        {
            'email': 'new@example.com',
            'password': 'Violet-River!83',
            'first_name': 'New',
            'last_name': 'User',
        },
        format='json',
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert 'access' in response.json()

    User = get_user_model()
    user = User.objects.get(email='new@example.com')
    assert user.first_name == 'New'


@pytest.mark.django_db
@pytest.mark.parametrize(
    'weak_password',
    ['short', 'password123', '12345678', 'Alexandra99', 42],
)
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_up_rejects_passwords_that_fail_the_configured_policy(
    mock_captcha, api_client, weak_password
):
    """Fails if sign-up creates an account after rejecting an unsafe password."""
    User = get_user_model()
    email = 'alexandra@example.com'

    response = api_client.post(
        reverse('sign_up'),
        {
            'email': email,
            'password': weak_password,
            'first_name': 'Alexandra',
            'last_name': 'Stone',
        },
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert isinstance(response.json()['error'], str)
    assert response.json()['error'] != ''
    assert User.objects.filter(email=email).exists() is False


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_in_requires_fields(mock_captcha, api_client):
    """Reject password sign-in requests that omit required fields."""
    response = api_client.post(reverse('sign_in'), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Email and password are required'


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_in_rejects_unknown_user(mock_captcha, api_client):
    """Return generic invalid credentials for an unknown email address."""
    response = api_client.post(
        reverse('sign_in'),
        {'email': 'missing@example.com', 'password': 'pass1234'},
        format='json',
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['error'] == 'Invalid credentials'


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_in_rejects_invalid_password(mock_captcha, api_client):
    """Reject a known user when the submitted password is incorrect."""
    User = get_user_model()
    User.objects.create_user(email='user@example.com', password='pass1234')

    response = api_client.post(
        reverse('sign_in'),
        {'email': 'user@example.com', 'password': 'wrong'},
        format='json',
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_in_rejects_inactive_user(mock_captcha, api_client):
    """Reject password sign-in for an inactive account."""
    User = get_user_model()
    user = User.objects.create_user(email='inactive@example.com', password='pass1234')
    user.is_active = False
    user.save(update_fields=['is_active'])

    response = api_client.post(
        reverse('sign_in'),
        {'email': 'inactive@example.com', 'password': 'pass1234'},
        format='json',
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['error'] == 'Account is inactive'


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_sign_in_success(mock_captcha, api_client):
    """Issue an access token for valid password credentials."""
    User = get_user_model()
    User.objects.create_user(email='active@example.com', password='pass1234')

    response = api_client.post(
        reverse('sign_in'),
        {'email': 'active@example.com', 'password': 'pass1234'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert 'access' in response.json()


@pytest.mark.django_db
def test_google_login_requires_credential(api_client):
    """Reject Google login when no provider credential is submitted."""
    response = api_client.post(reverse('google_login'), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Google credential is required'


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_invalid_credential_when_not_debug(api_client, monkeypatch):
    """Verifies Google login returns 401 when credential is invalid and the app is not in debug mode."""

    def fake_get(*_args, **_kwargs):
        return DummyResponse(status_code=500)

    monkeypatch.setattr(auth_views.requests, 'get', fake_get)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'bad-token', 'email': 'user@example.com'},
        format='json',
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['error'] == 'Invalid Google credential'


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_aud_mismatch_returns_error(api_client, monkeypatch):
    """Verifies Google login returns 401 when the token audience does not match the configured client ID."""

    def fake_get(*_args, **_kwargs):
        return DummyResponse(status_code=200, payload={'aud': 'other'})

    monkeypatch.setattr(auth_views.requests, 'get', fake_get)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'bad-aud', 'email': 'user@example.com'},
        format='json',
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['error'] == 'Invalid Google client'


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_google_login_requires_email_when_payload_missing(api_client, monkeypatch):
    """Verifies Google login returns 400 when the Google API call fails and no fallback email is provided."""

    def fake_get(*_args, **_kwargs):
        raise auth_views.requests.RequestException('fail')

    monkeypatch.setattr(auth_views.requests, 'get', fake_get)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'token'},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Email is required'


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_creates_user_with_payload(api_client, monkeypatch):
    """Verifies Google login creates a new user when the token payload contains a valid audience and email."""
    payload = {
        'aud': 'client-1',
        'email': 'google@example.com',
        'email_verified': True,
        'given_name': 'Google',
        'family_name': 'User',
        'picture': 'pic',
    }

    def fake_get(*_args, **_kwargs):
        return DummyResponse(status_code=200, payload=payload)

    monkeypatch.setattr(auth_views.requests, 'get', fake_get)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'token', 'email': 'other@example.com'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['created'] is True
    assert data['google_validated'] is True

    User = get_user_model()
    user = User.objects.get(email='google@example.com')
    assert user.first_name == 'Google'


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_updates_existing_user_names(api_client, monkeypatch):
    """Verifies Google login updates the first and last name of an existing user when the payload provides new values."""
    User = get_user_model()
    user = User.objects.create_user(email='existing@example.com', password='pass1234')
    user.first_name = ''
    user.last_name = ''
    user.save(update_fields=['first_name', 'last_name'])

    payload = {
        'aud': 'client-1',
        'email': 'existing@example.com',
        'email_verified': True,
        'given_name': 'Given',
        'family_name': 'Name',
    }

    def fake_get(*_args, **_kwargs):
        return DummyResponse(status_code=200, payload=payload)

    monkeypatch.setattr(auth_views.requests, 'get', fake_get)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'token'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['created'] is False

    user.refresh_from_db()
    assert user.first_name == 'Given'
    assert user.last_name == 'Name'


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_google_login_allows_debug_without_payload(api_client, monkeypatch):
    """Verifies Google login succeeds in debug mode using the fallback email when the Google API call fails."""

    def fake_get(*_args, **_kwargs):
        return DummyResponse(status_code=500)

    monkeypatch.setattr(auth_views.requests, 'get', fake_get)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'token', 'email': 'debug@example.com'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['google_validated'] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    'tokeninfo',
    [
        DummyResponse(payload={'email': 'google@example.com', 'email_verified': True}),
        DummyResponse(payload={'aud': 'other', 'email': 'google@example.com', 'email_verified': True}),
        DummyResponse(payload={'aud': 'client-1', 'email': ' ', 'email_verified': True}),
        DummyResponse(payload={'aud': 'client-1', 'email': 7, 'email_verified': True}),
        DummyResponse(payload={'aud': 'client-1', 'email': 'google@example.com', 'email_verified': False}),
        DummyResponse(payload={'aud': 'client-1', 'email': 'google@example.com'}),
        DummyResponse(payload={'aud': 'client-1', 'email': 'google@example.com', 'email_verified': 'false'}),
        DummyResponse(payload={'aud': 'client-1', 'email': 'google@example.com', 'email_verified': True, 'given_name': 9}),
        DummyResponse(payload={'aud': 'client-1', 'email': 'google@example.com', 'email_verified': True, 'family_name': []}),
        DummyResponse(payload=[]),
        DummyResponse(payload=None),
        DummyResponse(json_error=ValueError('not json')),
    ],
    ids=[
        'aud-missing', 'aud-mismatch', 'email-blank', 'email-non-string',
        'email-unverified-bool', 'email-unverified-missing', 'email-unverified-string',
        'given-name-non-string', 'family-name-non-string', 'json-list', 'json-null',
        'json-unparseable',
    ],
)
@override_settings(DEBUG=True, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_rejects_invalid_http_200_claims_without_using_hints(
    api_client, monkeypatch, tokeninfo
):
    """Fails if invalid tokeninfo claims can select a browser-supplied identity."""
    User = get_user_model()
    hinted = User.objects.create_user(
        email='hinted@example.com', password='pass1234', first_name='Original'
    )
    initial_ids = list(User.objects.values_list('pk', flat=True))
    monkeypatch.setattr(auth_views.requests, 'get', Mock(return_value=tokeninfo))

    response = api_client.post(
        reverse('google_login'),
        {
            'credential': 'token',
            'email': hinted.email,
            'given_name': 'Forged',
            'family_name': 'Identity',
        },
        format='json',
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert 'access' not in response.json()
    assert 'refresh' not in response.json()
    assert list(User.objects.values_list('pk', flat=True)) == initial_ids
    hinted.refresh_from_db()
    assert hinted.first_name == 'Original'


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='')
def test_google_login_rejects_an_unconfigured_production_client_before_tokeninfo(
    api_client, monkeypatch
):
    """Fails if production queries tokeninfo without a configured client audience."""
    tokeninfo = Mock()
    monkeypatch.setattr(auth_views.requests, 'get', tokeninfo)

    response = api_client.post(
        reverse('google_login'), {'credential': 'token', 'email': 'hinted@example.com'}, format='json'
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['error'] == 'Invalid Google client'
    tokeninfo.assert_not_called()


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_uses_the_verified_string_claim_identity_instead_of_hints(
    api_client, monkeypatch
):
    """Fails if a browser hint can replace the verified token email or token-owned names."""
    User = get_user_model()
    hinted = User.objects.create_user(
        email='hinted@example.com', password='pass1234', first_name='Hint', last_name='User'
    )
    payload = {
        'aud': 'client-1',
        'email': 'claimed@example.com',
        'email_verified': 'true',
        'given_name': 'Claimed',
        'family_name': 'Identity',
    }
    monkeypatch.setattr(auth_views.requests, 'get', Mock(return_value=DummyResponse(payload=payload)))

    response = api_client.post(
        reverse('google_login'),
        {
            'credential': 'token',
            'email': hinted.email,
            'given_name': 'Forged',
            'family_name': 'Names',
        },
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['google_validated'] is True
    claimed = User.objects.get(email='claimed@example.com')
    assert claimed.first_name == 'Claimed'
    assert claimed.last_name == 'Identity'
    hinted.refresh_from_db()
    assert hinted.first_name == 'Hint'
    assert hinted.last_name == 'User'


@pytest.mark.django_db
@pytest.mark.parametrize(
    'tokeninfo',
    [
        Mock(return_value=DummyResponse(status_code=500)),
        Mock(side_effect=auth_views.requests.RequestException('network unavailable')),
    ],
    ids=['provider-500', 'transport-error'],
)
@override_settings(DEBUG=True, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_uses_debug_transport_fallback_with_an_email(api_client, monkeypatch, tokeninfo):
    """Fails if DEBUG stops admitting the documented provider-failure fallback."""
    monkeypatch.setattr(auth_views.requests, 'get', tokeninfo)

    response = api_client.post(
        reverse('google_login'),
        {'credential': 'token', 'email': 'debug-transport@example.com'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['google_validated'] is False
    assert response.json()['access']
    assert response.json()['refresh']


@pytest.fixture
def totp_login_user(django_user_model):
    """Create an active user enrolled in TOTP for admission tests."""
    user = django_user_model.objects.create_user(
        email='totp-login@example.com', password='pass1234'
    )
    enrollment = twofactor.setup(user)
    twofactor.enable(user, pyotp.TOTP(enrollment['secret']).now())
    user.refresh_from_db()
    return user, enrollment['secret']


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_password_login_returns_a_second_factor_challenge_before_token_issuance(
    mock_captcha, api_client, totp_login_user
):
    """Fails if a password first factor issues JWTs before the enrolled TOTP check."""
    user, secret = totp_login_user
    outstanding_before = OutstandingToken.objects.count()

    first = api_client.post(
        reverse('sign_in'), {'email': user.email, 'password': 'pass1234'}, format='json'
    )

    assert first.status_code == status.HTTP_202_ACCEPTED
    assert set(first.json()) == {'requires_2fa', 'challenge'}
    assert first.json()['requires_2fa'] is True
    challenge = first.json()['challenge']
    assert isinstance(challenge, str)
    assert challenge != ''
    assert OutstandingToken.objects.count() == outstanding_before

    second = api_client.post(
        reverse('sign-in-2fa'),
        {'challenge': first.json()['challenge'], 'code': pyotp.TOTP(secret).now()},
        format='json',
    )

    assert second.status_code == status.HTTP_200_OK
    assert second.json()['access']
    assert second.json()['refresh']
    assert OutstandingToken.objects.count() == outstanding_before + 1
    refreshed = api_client.post('/api/token/refresh/', {'refresh': second.json()['refresh']}, format='json')
    assert refreshed.status_code == status.HTTP_200_OK
    assert refreshed.json()['access']


@pytest.mark.django_db
@override_settings(DEBUG=False, GOOGLE_OAUTH_CLIENT_ID='client-1')
def test_google_login_returns_a_second_factor_challenge_before_token_issuance(
    api_client, monkeypatch, totp_login_user
):
    """Fails if a validated Google first factor bypasses an enrolled TOTP check."""
    user, _secret = totp_login_user
    user.first_name = 'Original'
    user.last_name = 'Names'
    user.save(update_fields=['first_name', 'last_name'])
    outstanding_before = OutstandingToken.objects.count()
    organizations_before = Organization.objects.count()
    memberships_before = OrganizationMembership.objects.count()
    payload = {
        'aud': 'client-1',
        'email': user.email,
        'email_verified': True,
        'given_name': 'Claim',
        'family_name': 'Names',
    }
    monkeypatch.setattr(auth_views.requests, 'get', Mock(return_value=DummyResponse(payload=payload)))

    response = api_client.post(reverse('google_login'), {'credential': 'token'}, format='json')

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert set(response.json()) == {'requires_2fa', 'challenge'}
    assert response.json()['requires_2fa'] is True
    challenge = response.json()['challenge']
    assert isinstance(challenge, str)
    assert challenge != ''
    assert OutstandingToken.objects.count() == outstanding_before
    assert Organization.objects.count() == organizations_before
    assert OrganizationMembership.objects.count() == memberships_before
    user.refresh_from_db()
    assert user.first_name == 'Original'
    assert user.last_name == 'Names'


@pytest.mark.django_db
def test_send_passcode_requires_email(api_client):
    """Reject password-reset passcode requests without an email."""
    response = api_client.post(reverse('send_passcode'), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Email is required'


@pytest.mark.django_db
def test_send_passcode_returns_generic_message_for_missing_user(api_client):
    """Hide whether a password-reset email belongs to an account."""
    response = api_client.post(
        reverse('send_passcode'),
        {'email': 'missing@example.com'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['message'] == 'If the email exists, a code has been sent'
    assert PasswordCode.objects.count() == 0


@pytest.mark.django_db
def test_send_passcode_success(api_client, monkeypatch):
    """Persist a passcode when the reset email boundary succeeds."""
    User = get_user_model()
    user = User.objects.create_user(email='send@example.com', password='pass1234')

    monkeypatch.setattr(auth_views, 'send_password_reset_code', lambda *_args, **_kwargs: True)

    response = api_client.post(
        reverse('send_passcode'),
        {'email': user.email},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert PasswordCode.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_send_passcode_failure(api_client, monkeypatch):
    """Report an email delivery failure when sending a reset passcode."""
    User = get_user_model()
    user = User.objects.create_user(email='fail@example.com', password='pass1234')

    monkeypatch.setattr(auth_views, 'send_password_reset_code', lambda *_args, **_kwargs: False)

    response = api_client.post(
        reverse('send_passcode'),
        {'email': user.email},
        format='json',
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.json()['error'] == 'Failed to send email'


@pytest.mark.django_db
def test_verify_passcode_requires_fields(api_client):
    """Reject passcode verification when required fields are absent."""
    response = api_client.post(reverse('verify_passcode_reset'), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Email, code, and new password are required'


@pytest.mark.django_db
def test_verify_passcode_rejects_invalid_email(api_client):
    """Reject passcode verification for an unknown email address."""
    response = api_client.post(
        reverse('verify_passcode_reset'),
        {'email': 'missing@example.com', 'code': '123456', 'new_password': 'newpass'},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@freeze_time('2026-01-15 10:00:00')
def test_verify_passcode_rejects_expired_code(api_client):
    """Verifies passcode verification returns 400 when the code was created more than 15 minutes ago."""
    User = get_user_model()
    user = User.objects.create_user(email='expired@example.com', password='pass1234')
    password_code = PasswordCode.objects.create(user=user, code='111111')
    PasswordCode.objects.filter(id=password_code.id).update(
        created_at=timezone.now() - timedelta(minutes=16)
    )

    response = api_client.post(
        reverse('verify_passcode_reset'),
        {'email': user.email, 'code': '111111', 'new_password': 'newpass'},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Invalid or expired code'


@pytest.mark.django_db
def test_verify_passcode_handles_exception(api_client, monkeypatch):
    """Verifies passcode verification returns 400 when an unexpected exception occurs during code validation."""
    User = get_user_model()
    user = User.objects.create_user(email='boom@example.com', password='pass1234')
    PasswordCode.objects.create(user=user, code='222222')

    def boom(_self):
        raise Exception('boom')

    monkeypatch.setattr(PasswordCode, 'is_valid', boom)

    response = api_client.post(
        reverse('verify_passcode_reset'),
        {'email': user.email, 'code': '222222', 'new_password': 'newpass'},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Invalid or expired code'


@pytest.mark.django_db
def test_verify_passcode_resets_password(api_client):
    """Verifies passcode verification resets the user password and marks the code as used on success."""
    User = get_user_model()
    user = User.objects.create_user(email='reset@example.com', password='pass1234')
    password_code = PasswordCode.objects.create(user=user, code='333333')

    response = api_client.post(
        reverse('verify_passcode_reset'),
        {'email': user.email, 'code': '333333', 'new_password': 'NewPass!2026'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    password_code.refresh_from_db()
    user.refresh_from_db()

    assert password_code.used is True
    assert user.check_password('NewPass!2026') is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    'weak_password',
    ['short', 'password123', '12345678', 'Alexandra99', 42],
)
def test_verify_passcode_keeps_valid_code_after_password_policy_rejection(
    api_client, weak_password
):
    """Fails if a rejected password consumes a reset code before a valid retry."""
    User = get_user_model()
    user = User.objects.create_user(
        email='reset-policy@example.com',
        password='Violet-River!83',
        first_name='Alexandra',
        last_name='Stone',
    )
    password_code = PasswordCode.objects.create(user=user, code='444444')

    rejected_response = api_client.post(
        reverse('verify_passcode_reset'),
        {'email': user.email, 'code': password_code.code, 'new_password': weak_password},
        format='json',
    )

    assert rejected_response.status_code == status.HTTP_400_BAD_REQUEST
    password_code.refresh_from_db()
    user.refresh_from_db()
    assert password_code.used is False
    assert user.check_password('Violet-River!83') is True

    accepted_response = api_client.post(
        reverse('verify_passcode_reset'),
        {'email': user.email, 'code': password_code.code, 'new_password': 'NewPass!2026'},
        format='json',
    )

    assert accepted_response.status_code == status.HTTP_200_OK
    password_code.refresh_from_db()
    user.refresh_from_db()
    assert password_code.used is True
    assert user.check_password('NewPass!2026') is True


def _reset_with(api_client, email, code, new_password='NewPass!2026'):
    return api_client.post(
        reverse('verify_passcode_reset'),
        {'email': email, 'code': code, 'new_password': new_password},
        format='json',
    )


@pytest.mark.django_db
def test_verify_passcode_wrong_code_invalidates_the_pending_code(api_client):
    """Fails if a wrong guess leaves the account's pending code usable."""
    User = get_user_model()
    user = User.objects.create_user(email='guess@example.com', password='Violet-River!83')
    pending = PasswordCode.objects.create(user=user, code='555555')

    response = _reset_with(api_client, user.email, '000000')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Invalid or expired code'
    pending.refresh_from_db()
    assert pending.used is True


@pytest.mark.django_db
def test_verify_passcode_rejects_the_right_code_after_a_wrong_guess(api_client):
    """Fails if an account tolerates more than one wrong guess per issued code."""
    User = get_user_model()
    user = User.objects.create_user(email='guess-twice@example.com', password='Violet-River!83')
    PasswordCode.objects.create(user=user, code='555555')
    _reset_with(api_client, user.email, '000000')

    response = _reset_with(api_client, user.email, '555555')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    user.refresh_from_db()
    assert user.check_password('Violet-River!83') is True


@pytest.mark.django_db
def test_verify_passcode_wrong_code_keeps_other_accounts_codes(api_client):
    """Fails if a wrong guess burns codes beyond the targeted account."""
    User = get_user_model()
    target = User.objects.create_user(email='target@example.com', password='Violet-River!83')
    bystander = User.objects.create_user(email='bystander@example.com', password='Amber-Cloud!74')
    PasswordCode.objects.create(user=target, code='555555')
    bystander_code = PasswordCode.objects.create(user=bystander, code='666666')

    _reset_with(api_client, target.email, '000000')

    bystander_code.refresh_from_db()
    assert bystander_code.used is False


@pytest.mark.django_db
def test_verify_passcode_rejects_a_superseded_code(api_client, monkeypatch):
    """Fails if an earlier code still resets the password after a reissue."""
    User = get_user_model()
    user = User.objects.create_user(email='superseded@example.com', password='Violet-River!83')
    issued = iter([111111, 222222])
    monkeypatch.setattr(secrets, 'randbelow', lambda _bound: next(issued))
    first = PasswordCode.generate_code(user)
    PasswordCode.generate_code(user)

    response = _reset_with(api_client, user.email, first.code)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    user.refresh_from_db()
    assert user.check_password('Violet-River!83') is True


@pytest.mark.django_db
def test_verify_passcode_accepts_the_latest_code_after_a_reissue(api_client):
    """Fails if superseding earlier codes also disables the newly issued one."""
    User = get_user_model()
    user = User.objects.create_user(email='latest@example.com', password='Violet-River!83')
    PasswordCode.generate_code(user)
    latest = PasswordCode.generate_code(user)

    response = _reset_with(api_client, user.email, latest.code)

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.check_password('NewPass!2026') is True


@pytest.mark.django_db
def test_update_password_requires_fields(api_client):
    """Reject authenticated password updates with missing passwords."""
    User = get_user_model()
    user = User.objects.create_user(email='update-fields@example.com', password='pass1234')
    api_client.force_authenticate(user=user)

    response = api_client.post(reverse('update_password'), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Current password and new password are required'


@pytest.mark.django_db
def test_update_password_rejects_wrong_current(api_client):
    """Reject a password update when the current password is incorrect."""
    User = get_user_model()
    user = User.objects.create_user(email='update@example.com', password='pass1234')

    api_client.force_authenticate(user=user)

    response = api_client.post(
        reverse('update_password'),
        {'current_password': 'wrong', 'new_password': 'newpass'},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error'] == 'Current password is incorrect'


@pytest.mark.django_db
def test_update_password_success(api_client):
    """Verifies update-password endpoint successfully changes the user password when the current password is correct."""
    User = get_user_model()
    user = User.objects.create_user(email='update2@example.com', password='pass1234')

    api_client.force_authenticate(user=user)

    response = api_client.post(
        reverse('update_password'),
        {'current_password': 'pass1234', 'new_password': 'NewPass!2026'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.check_password('NewPass!2026') is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    'weak_password',
    ['short', 'password123', '12345678', 'Alexandra99', 42],
)
def test_update_password_preserves_hash_when_new_password_fails_policy(
    api_client, weak_password
):
    """Fails if an unsafe new password changes the hash before the request is rejected."""
    User = get_user_model()
    user = User.objects.create_user(
        email='update-policy@example.com',
        password='Violet-River!83',
        first_name='Alexandra',
        last_name='Stone',
    )
    api_client.force_authenticate(user=user)

    rejected_response = api_client.post(
        reverse('update_password'),
        {'current_password': 'Violet-River!83', 'new_password': weak_password},
        format='json',
    )

    assert rejected_response.status_code == status.HTTP_400_BAD_REQUEST
    assert isinstance(rejected_response.json()['error'], str)
    assert rejected_response.json()['error'] != ''
    user.refresh_from_db()
    assert user.check_password('Violet-River!83') is True

    accepted_response = api_client.post(
        reverse('update_password'),
        {'current_password': 'Violet-River!83', 'new_password': 'NewPass!2026'},
        format='json',
    )

    assert accepted_response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.check_password('NewPass!2026') is True


@pytest.mark.django_db
def test_validate_token_requires_auth(api_client):
    """Require authentication before validating a session token."""
    response = api_client.get(reverse('validate_token'))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_validate_token_success(api_client):
    """Confirm that an authenticated session token is valid."""
    User = get_user_model()
    user = User.objects.create_user(email='token@example.com', password='pass1234')

    api_client.force_authenticate(user=user)
    response = api_client.get(reverse('validate_token'))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['valid'] is True
