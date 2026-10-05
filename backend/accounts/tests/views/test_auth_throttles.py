"""Authentication attempt budget across every public and TOTP entry point."""

from __future__ import annotations

import copy
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status

from accounts.models import PasswordCode
from accounts.throttles import AuthThrottle

AUTH_IP = '198.51.100.24'
OTHER_AUTH_IP = '198.51.100.25'
PUBLIC_AUTH_REQUESTS = (
    pytest.param('/api/token/', {'email': 'quota@example.com', 'password': 'wrongpass'}, id='token-obtain'),
    pytest.param('/api/token/refresh/', {'refresh': 'not-a-refresh-token'}, id='token-refresh'),
    pytest.param('/api/sign_up/', {}, id='sign-up'),
    pytest.param('/api/sign_in/', {'email': 'quota@example.com', 'password': 'wrongpass'}, id='sign-in'),
    pytest.param('/api/google_login/', {}, id='google-login'),
    pytest.param('/api/send_passcode/', {}, id='send-passcode'),
    pytest.param('/api/verify_passcode_and_reset_password/', {}, id='verify-passcode'),
    pytest.param('/api/sign_in/2fa/', {}, id='sign-in-2fa'),
)
TWO_FACTOR_AUTH_REQUESTS = (
    pytest.param('/api/me/2fa/enable/', {}, id='twofa-enable'),
    pytest.param('/api/me/2fa/disable/', {}, id='twofa-disable'),
)


@pytest.fixture(autouse=True)
def _use_five_attempt_auth_rate(settings):
    """Give quota examples their contractual five-per-minute rate."""
    original_framework = copy.deepcopy(settings.REST_FRAMEWORK)
    framework = copy.deepcopy(settings.REST_FRAMEWORK)
    rates = dict(framework.get('DEFAULT_THROTTLE_RATES', {}))
    rates['auth'] = '5/min'
    framework['DEFAULT_THROTTLE_RATES'] = rates
    settings.REST_FRAMEWORK = framework
    cache.clear()

    yield

    cache.clear()
    settings.REST_FRAMEWORK = original_framework


def _post_from_ip(client, url, payload, ip_address=AUTH_IP):
    return client.post(url, payload, format='json', REMOTE_ADDR=ip_address)


def _consume_auth_quota(client, url, payload, ip_address=AUTH_IP):
    for _ in range(5):
        _post_from_ip(client, url, payload, ip_address)


@pytest.mark.django_db
@pytest.mark.parametrize(('url', 'payload'), PUBLIC_AUTH_REQUESTS)
def test_public_auth_entry_point_rejects_the_sixth_attempt(api_client, url, payload):
    """Fails if a public authentication route omits the shared five-attempt throttle."""
    # Arrange
    _consume_auth_quota(api_client, url, payload)

    # Act
    response = _post_from_ip(api_client, url, payload)

    # Assert
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response['Retry-After'] != ''


@pytest.mark.django_db
@pytest.mark.parametrize(('url', 'payload'), TWO_FACTOR_AUTH_REQUESTS)
def test_authenticated_totp_entry_point_rejects_the_sixth_attempt(
    api_client,
    existing_user,
    url,
    payload,
):
    """Fails if an authenticated TOTP endpoint omits the shared attempt throttle."""
    # Arrange
    api_client.force_authenticate(user=existing_user)
    _consume_auth_quota(api_client, url, payload)

    # Act
    response = _post_from_ip(api_client, url, payload)

    # Assert
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response['Retry-After'] != ''


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_auth_quota_blocks_jwt_obtain_after_sign_in(mock_recaptcha, api_client):
    """Fails if separate route keys let an attacker evade the login quota."""
    # Arrange
    sign_in_url = reverse('sign_in')
    token_url = reverse('token_obtain_pair')
    credentials = {'email': 'quota@example.com', 'password': 'wrongpass'}
    _consume_auth_quota(api_client, sign_in_url, credentials)

    # Act
    response = _post_from_ip(api_client, token_url, credentials)

    # Assert
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response['Retry-After'] != ''


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_throttled_password_reset_creates_no_recovery_code(mock_recaptcha, api_client, django_user_model):
    """Fails if quota rejection happens after password-reset persistence."""
    # Arrange
    user = django_user_model.objects.create_user(
        email='reset-quota@example.com', password='pass1234'
    )
    credentials = {'email': 'quota@example.com', 'password': 'wrongpass'}
    _consume_auth_quota(api_client, reverse('sign_in'), credentials)

    # Act
    with patch('accounts.views.auth.send_password_reset_code', return_value=True) as send_reset:
        response = _post_from_ip(
            api_client,
            reverse('send_passcode'),
            {'email': user.email},
        )

    # Assert
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response['Retry-After'] != ''
    assert PasswordCode.objects.filter(user=user).count() == 0
    send_reset.assert_not_called()


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_auth_quota_allows_an_independent_ip(mock_recaptcha, api_client):
    """Fails if one caller exhausts authentication attempts for another IP address."""
    # Arrange
    credentials = {'email': 'quota@example.com', 'password': 'wrongpass'}
    _consume_auth_quota(api_client, reverse('sign_in'), credentials)

    # Act
    response = _post_from_ip(
        api_client,
        reverse('sign_in'),
        credentials,
        ip_address=OTHER_AUTH_IP,
    )

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
@patch('accounts.views.auth.verify_recaptcha', return_value=True)
def test_auth_quota_allows_an_attempt_after_its_window_expires(mock_recaptcha, api_client, monkeypatch):
    """Fails if expired attempt timestamps continue blocking a later login request."""
    # Arrange
    credentials = {'email': 'quota@example.com', 'password': 'wrongpass'}
    monkeypatch.setattr(AuthThrottle, 'timer', staticmethod(lambda: 1_700_000_000))
    _consume_auth_quota(api_client, reverse('sign_in'), credentials)
    monkeypatch.setattr(AuthThrottle, 'timer', staticmethod(lambda: 1_700_000_061))

    # Act
    response = _post_from_ip(api_client, reverse('sign_in'), credentials)

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
