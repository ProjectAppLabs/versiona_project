"""JWT admission contracts for regular, inactive, and TOTP-enrolled accounts."""

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from accounts import twofactor


@pytest.mark.django_db
def test_token_obtain_pair_with_email_success(api_client):
    """Fails if JWT obtain stops issuing a pair for an active account without TOTP."""
    # Arrange
    User = get_user_model()
    User.objects.create_user(email='token@example.com', password='pass1234')

    # Act
    url = reverse('token_obtain_pair')
    response = api_client.post(url, {'email': 'token@example.com', 'password': 'pass1234'}, format='json')

    # Assert
    assert response.status_code == status.HTTP_200_OK
    assert set(response.json()) == {'access', 'refresh'}
    assert response.json()['access'] != ''
    assert response.json()['refresh'] != ''


@pytest.mark.django_db
def test_token_obtain_pair_returns_challenge_for_an_enrolled_account(api_client):
    """Fails if JWT obtain bypasses TOTP or mints a session before the second factor."""
    # Arrange
    User = get_user_model()
    user = User.objects.create_user(email='jwt-totp@example.com', password='pass1234')
    enrollment = twofactor.setup(user)
    twofactor.enable(user, pyotp.TOTP(enrollment['secret']).now())
    outstanding_before = OutstandingToken.objects.count()

    # Act
    response = api_client.post(
        reverse('token_obtain_pair'),
        {'email': user.email, 'password': 'pass1234'},
        format='json',
    )

    # Assert
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert set(response.json()) == {'requires_2fa', 'challenge'}
    assert response.json()['requires_2fa'] is True
    assert response.json()['challenge'] != ''
    assert OutstandingToken.objects.count() == outstanding_before


@pytest.mark.django_db
def test_token_obtain_pair_rejects_an_inactive_account(api_client):
    """Fails if JWT admission authenticates an account that has been deactivated."""
    # Arrange
    User = get_user_model()
    User.objects.create_user(
        email='inactive-jwt@example.com',
        password='pass1234',
        is_active=False,
    )

    # Act
    response = api_client.post(
        reverse('token_obtain_pair'),
        {'email': 'inactive-jwt@example.com', 'password': 'pass1234'},
        format='json',
    )

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert 'access' not in response.json()
    assert 'refresh' not in response.json()


@pytest.mark.django_db
def test_token_obtain_pair_rejects_invalid_credentials_without_creating_a_session(api_client):
    """Fails if invalid JWT credentials create an outstanding refresh-token session."""
    # Arrange
    User = get_user_model()
    User.objects.create_user(email='wrong-password@example.com', password='pass1234')
    outstanding_before = OutstandingToken.objects.count()

    # Act
    response = api_client.post(
        reverse('token_obtain_pair'),
        {'email': 'wrong-password@example.com', 'password': 'not-the-password'},
        format='json',
    )

    # Assert
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert OutstandingToken.objects.count() == outstanding_before


@pytest.mark.django_db
def test_jwt_totp_challenge_allows_refresh_after_second_factor(api_client):
    """Fails if a completed JWT TOTP challenge cannot mint a usable refresh session."""
    # Arrange
    User = get_user_model()
    user = User.objects.create_user(email='jwt-roundtrip@example.com', password='pass1234')
    enrollment = twofactor.setup(user)
    twofactor.enable(user, pyotp.TOTP(enrollment['secret']).now())
    first = api_client.post(
        reverse('token_obtain_pair'),
        {'email': user.email, 'password': 'pass1234'},
        format='json',
    )

    # Act
    second = api_client.post(
        reverse('sign-in-2fa'),
        {
            'challenge': first.json()['challenge'],
            'code': pyotp.TOTP(enrollment['secret']).now(),
        },
        format='json',
    )
    refreshed = api_client.post(
        reverse('token_refresh'),
        {'refresh': second.json()['refresh']},
        format='json',
    )

    # Assert
    assert first.status_code == status.HTTP_202_ACCEPTED
    assert second.status_code == status.HTTP_200_OK
    assert refreshed.status_code == status.HTTP_200_OK
    assert refreshed.json()['access'] != ''


@pytest.mark.django_db
@pytest.mark.parametrize('version', [0, 3])
def test_jwt_alias_mints_the_authenticated_epoch(api_client, django_user_model, version):
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
    user = django_user_model.objects.create_user(email='epoch@example.com', password='pass1234', auth_version=version)
    response = api_client.post(reverse('token_obtain_pair'), {'email': user.email, 'password': 'pass1234'}, format='json')
    assert response.status_code == 200
    assert AccessToken(response.data['access'])['auth_version'] == version
    assert RefreshToken(response.data['refresh'])['auth_version'] == version


@pytest.mark.django_db
@pytest.mark.parametrize('version,expected', [(0, 200), (1, 401)])
def test_legacy_access_only_admits_an_unrotated_account(api_client, django_user_model, version, expected):
    from rest_framework_simplejwt.tokens import RefreshToken
    user = django_user_model.objects.create_user(email='legacy@example.com', auth_version=version)
    token = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    assert api_client.get(reverse('validate_token')).status_code == expected


@pytest.mark.django_db
@pytest.mark.parametrize('version,expected', [(0, 200), (1, 401)])
def test_legacy_refresh_only_admits_an_unrotated_account(api_client, django_user_model, version, expected):
    from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
    user = django_user_model.objects.create_user(email='legacy-refresh@example.com', auth_version=version)
    token = RefreshToken.for_user(user)
    response = api_client.post(reverse('token_refresh'), {'refresh': str(token)}, format='json')
    assert response.status_code == expected


@pytest.mark.django_db
def test_minting_does_not_upgrade_a_previously_authenticated_password(api_client, django_user_model):
    from accounts.utils.auth_utils import generate_auth_tokens
    user = django_user_model.objects.create_user(email='stale-instance@example.com', password='pass1234')
    django_user_model.objects.filter(pk=user.pk).update(auth_version=1)
    pair = generate_auth_tokens(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {pair['access']}")
    assert api_client.get(reverse('validate_token')).status_code == 401


@pytest.mark.django_db
def test_password_update_revokes_the_current_access(api_client, django_user_model):
    from accounts.utils.auth_utils import generate_auth_tokens
    user = django_user_model.objects.create_user(email='update-session@example.com', password='pass1234')
    pair = generate_auth_tokens(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {pair['access']}")
    response = api_client.post(reverse('update_password'), {'current_password': 'pass1234', 'new_password': 'Updated-Mountain!91'}, format='json')
    assert response.status_code == 200
    assert api_client.get(reverse('validate_token')).status_code == 401
