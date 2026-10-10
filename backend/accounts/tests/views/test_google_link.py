"""Email possession, provider subject and session rotation are independent proofs."""
import time
from unittest.mock import Mock

import pyotp
import pytest
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken

from accounts import twofactor
from accounts.models import PasswordCode
from accounts.services import google_identity_service as google
from accounts.utils.auth_utils import generate_auth_tokens

CURRENT = 'Recover-River!82'
REPLACEMENT = 'Connect-Mountain!93'
pytestmark = pytest.mark.django_db


@pytest.fixture
def identity_boundary(settings, monkeypatch):
    """Provide verified Google claims only at the external tokeninfo boundary."""
    settings.GOOGLE_OAUTH_CLIENT_ID = 'test-google-client'
    payload = {'sub': 'opaque-Subject-A', 'aud': 'test-google-client',
               'iss': 'https://accounts.google.com', 'exp': str(int(time.time()) + 3600),
               'email': 'owner@example.com', 'email_verified': 'true'}
    transport = Mock(return_value=Mock(status_code=200, json=Mock(return_value=payload)))
    monkeypatch.setattr(google.requests, 'get', transport)
    return payload


@pytest.fixture
def recovered(api_client, django_user_model):
    """Recover email ownership and retain sessions from before and after recovery."""
    user = django_user_model.objects.create_user(email='owner@example.com', password='Attacker-Chosen!51')
    stolen = generate_auth_tokens(user)
    code = PasswordCode.objects.create(user=user, code='123456')
    response = api_client.post(reverse('verify_passcode_reset'), {
        'email': user.email, 'code': code.code, 'new_password': CURRENT,
    }, format='json')
    assert response.status_code == 200
    user.refresh_from_db()
    pair = generate_auth_tokens(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {pair['access']}")
    body = {'credential': 'verified-at-boundary', 'google_link_ticket': response.data['google_link_ticket'],
            'current_password': CURRENT, 'new_password': REPLACEMENT}
    return user, body, stolen, pair


def test_preregistration_requires_recovery_without_mutating_account(api_client, django_user_model, identity_boundary):
    """Reject email-based Google admission without changing the preregistered account."""
    user = django_user_model.objects.create_user(email='owner@example.com', password='Attacker-Chosen!51', first_name='Original')
    before = (user.password, OutstandingToken.objects.count())
    response = api_client.post(reverse('google_login'), {'credential': 'verified-at-boundary'}, format='json')
    assert response.status_code == 409
    assert response.data['code'] == 'google_link_required'
    assert 'user' not in response.data
    assert 'access' not in response.data
    user.refresh_from_db()
    assert (user.password, OutstandingToken.objects.count()) == before
    assert user.first_name == 'Original'
    assert user.google_subject is None


def test_current_password_without_email_recovery_cannot_link(api_client, django_user_model, identity_boundary):
    """Reject linking when possession of the current password lacks email recovery proof."""
    user = django_user_model.objects.create_user(email='owner@example.com', password=CURRENT)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_auth_tokens(user)['access']}")
    response = api_client.post(reverse('google-link'), {'credential': 'verified-at-boundary',
        'current_password': CURRENT, 'new_password': REPLACEMENT}, format='json')
    assert response.status_code == 403
    user.refresh_from_db()
    assert user.google_subject is None


def test_recovery_revokes_the_preregistered_access_token(api_client, recovered):
    """Reject an access token minted before email recovery."""
    _, _, stolen, _ = recovered
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {stolen['access']}")
    assert api_client.get(reverse('validate_token')).status_code == 401


def test_recovery_revokes_the_preregistered_refresh_token(api_client, recovered):
    """Reject a refresh token minted before email recovery."""
    _, _, stolen, _ = recovered
    response = api_client.post(reverse('token_refresh'), {'refresh': stolen['refresh']}, format='json')
    assert response.status_code == 401


def test_explicit_link_returns_a_pair_for_the_new_epoch(api_client, recovered, identity_boundary):
    """Admit the linked session while rejecting tokens from the preceding epoch."""
    user, body, _, pair = recovered
    response = api_client.post(reverse('google-link'), body, format='json')
    assert response.status_code == 201
    user.refresh_from_db()
    assert user.google_subject == 'opaque-Subject-A'
    assert user.check_password(REPLACEMENT)
    assert user.auth_version == 2
    assert AccessToken(response.data['access'])['auth_version'] == 2
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {pair['access']}")
    assert api_client.get(reverse('validate_token')).status_code == 401
    assert api_client.post(reverse('token_refresh'), {'refresh': pair['refresh']}, format='json').status_code == 401
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert api_client.get(reverse('validate_token')).status_code == 200


@pytest.mark.parametrize(('field', 'value', 'expected'), [
    ('current_password', 'wrong-password', 403),
    ('new_password', CURRENT, 400),
    ('new_password', '12345678', 400),
    ('google_link_ticket', 'forged', 403),
])
def test_rejected_link_keeps_credentials(api_client, recovered, identity_boundary, field, value, expected):
    """Preserve the account credentials when a linking proof or replacement is invalid."""
    user, body, _, _ = recovered
    body[field] = value
    response = api_client.post(reverse('google-link'), body, format='json')
    assert response.status_code == expected
    user.refresh_from_db()
    assert user.google_subject is None
    assert user.auth_version == 1
    assert user.check_password(CURRENT)


def test_different_google_email_cannot_link(api_client, recovered, identity_boundary):
    """Reject provider claims whose email differs from the recovered account."""
    identity_boundary['email'] = 'other@example.com'
    response = api_client.post(reverse('google-link'), recovered[1], format='json')
    assert response.status_code == 409
    recovered[0].refresh_from_db()
    assert recovered[0].google_subject is None


def test_ticket_bound_to_another_user_cannot_link(api_client, recovered, identity_boundary, django_user_model):
    """Reject a recovery ticket belonging to another authenticated account."""
    other = django_user_model.objects.create_user(email='other@example.com', password=CURRENT, auth_version=1)
    recovered[1]['google_link_ticket'] = google.issue_link_ticket(other)
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 403


def test_expired_email_recovery_ticket_cannot_link(api_client, recovered, identity_boundary, monkeypatch):
    """Reject an expired recovery ticket despite a live provider credential."""
    real_time = time.time
    with monkeypatch.context() as old_clock:
        old_clock.setattr(signing.time, 'time', lambda: real_time() - 901)
        recovered[1]['google_link_ticket'] = google.issue_link_ticket(recovered[0])
    # Provider credential remains live; only the recovery ticket expires.
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 403


def test_consumed_ticket_cannot_link_again(api_client, recovered, identity_boundary):
    """Reject reuse of the recovery ticket after successful linking."""
    response = api_client.post(reverse('google-link'), recovered[1], format='json')
    assert response.status_code == 201
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 403


def test_occupied_subject_cannot_link(api_client, recovered, identity_boundary, django_user_model):
    """Reject a Google identity already owned by a different account."""
    django_user_model.objects.create_user(email='other@example.com', google_subject=identity_boundary['sub'])
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 409


def test_active_totp_is_preserved_by_link(api_client, recovered, identity_boundary):
    """Keep the enrolled TOTP identity exactly unchanged while revoking its old challenge."""
    user, body, _, _ = recovered
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled_at = timezone.now()
    user.save(update_fields=['totp_secret', 'totp_enabled_at'])
    user.refresh_from_db()
    original_secret = user.totp_secret
    original_enabled_at = user.totp_enabled_at
    challenge = twofactor.issue_challenge(user)
    body['code'] = pyotp.TOTP(user.totp_secret).now()
    assert api_client.post(reverse('google-link'), body, format='json').status_code == 201
    user.refresh_from_db()
    assert user.totp_enabled_at == original_enabled_at
    assert user.totp_secret == original_secret
    from documents.services.version_service import DomainError
    with pytest.raises(DomainError):
        twofactor.resolve_challenge(challenge)


def test_missing_active_totp_keeps_identity_unlinked(api_client, recovered, identity_boundary):
    """Reject linking without the enrolled second factor."""
    user = recovered[0]
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled_at = timezone.now()
    user.save(update_fields=['totp_secret', 'totp_enabled_at'])
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 403
    user.refresh_from_db()
    assert user.google_subject is None


def test_subject_authenticates_after_provider_email_changes(api_client, recovered, identity_boundary):
    """Authenticate the linked provider subject after its Google email changes."""
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 201
    api_client.credentials()
    identity_boundary['email'] = 'changed-at-google@example.com'
    response = api_client.post(reverse('google_login'), {'credential': 'verified-at-boundary'}, format='json')
    assert response.status_code == 200
    assert response.data['user']['email'] == 'owner@example.com'


def test_google_subject_comparison_is_case_sensitive(api_client, recovered, identity_boundary):
    """Treat differently cased provider subjects as distinct identities."""
    assert api_client.post(reverse('google-link'), recovered[1], format='json').status_code == 201
    api_client.credentials()
    identity_boundary['sub'] = identity_boundary['sub'].lower()
    response = api_client.post(reverse('google_login'), {'credential': 'verified-at-boundary'}, format='json')
    assert response.status_code == 409


def test_link_consumes_a_backup_factor(api_client, recovered, identity_boundary):
    """Consume a backup factor once during linking and reject its subsequent reuse."""
    user, body, _, _ = recovered
    backup = 'abc1-def2'
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled_at = timezone.now()
    user.totp_backup_codes = [twofactor._hash_code(backup)]
    user.save(update_fields=['totp_secret', 'totp_enabled_at', 'totp_backup_codes'])
    body['code'] = backup
    response = api_client.post(reverse('google-link'), body, format='json')
    assert response.status_code == 201
    user.refresh_from_db()
    assert user.totp_backup_codes == []
    assert twofactor.verify_code(user, backup) is False


def test_new_google_account_persists_subject_without_local_password(api_client, identity_boundary, django_user_model):
    """Persist a new provider identity without creating usable local credentials."""
    response = api_client.post(reverse('google_login'), {'credential': 'verified-at-boundary'}, format='json')
    assert response.status_code == 200
    user = django_user_model.objects.get(email='owner@example.com')
    assert user.google_subject == 'opaque-Subject-A'
    assert user.has_usable_password() is False
    assert response.data['created'] is True
