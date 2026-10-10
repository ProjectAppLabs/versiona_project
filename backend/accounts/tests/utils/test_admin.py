"""Admin recovery-code permissions and authorized impersonation admission."""

import pytest
from core.admin_site import admin_site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from accounts.admin import PasswordCodeAdmin, VersionaUserAdmin
from accounts.models import PasswordCode, User


def _request_with_messages(user):
    request = RequestFactory().get('/admin/')
    request.user = user
    request.session = {}
    setattr(request, '_messages', FallbackStorage(request))
    return request


@pytest.mark.django_db
def test_password_code_admin_disables_add_permission():
    """Prevent administrators from creating password recovery codes through the admin form."""
    admin = PasswordCodeAdmin(PasswordCode, admin_site)
    request = RequestFactory().get('/admin/')

    assert admin.has_add_permission(request) is False


@pytest.mark.django_db
def test_admin_site_custom_sections():
    """Verifies the custom admin site exposes the curated model sections in the app list."""
    User.objects.create_superuser(email='admin@example.com', password='pass1234')
    request = RequestFactory().get('/admin/')
    request.user = User.objects.get(email='admin@example.com')

    app_list = admin_site.get_app_list(request)

    object_names = {model['object_name'] for section in app_list for model in section['models']}

    assert {'User', 'PasswordCode', 'StagingPhaseBanner'}.issubset(object_names)


@pytest.mark.django_db
def test_user_admin_login_as_link_renders_admin_url():
    """Render the impersonation link for the target account admin route."""
    user = User.objects.create_user(email='target@example.com', password='pass1234')
    admin = VersionaUserAdmin(User, admin_site)

    html = admin.login_as_link(user)

    assert 'Login as this user' in html
    assert f'/admin/accounts/user/{user.id}/login_as/' in html


@pytest.mark.django_db
def test_user_admin_login_as_redirects_to_frontend(settings):
    """Redirect authorized impersonation with tokens stamped for the target account epoch."""
    factory = RequestFactory()
    admin_user = User.objects.create_superuser(email='admin@example.com', password='pass1234')
    target_user = User.objects.create_user(email='target@example.com', password='pass1234')
    request = factory.get('/admin/')
    request.user = admin_user
    settings.FRONTEND_URL = 'http://localhost:3000'

    admin = VersionaUserAdmin(User, admin_site)
    response = admin.login_as_user_view(request, target_user.id)

    assert response.status_code == 302
    assert response['Location'].startswith('http://localhost:3000/admin-login?')
    assert 'access=' in response['Location']
    assert 'refresh=' in response['Location']
    assert 'redirect=%2F' in response['Location']
    from urllib.parse import parse_qs, urlparse

    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
    query = parse_qs(urlparse(response['Location']).query)
    assert AccessToken(query['access'][0])['auth_version'] == target_user.auth_version
    assert RefreshToken(query['refresh'][0])['auth_version'] == target_user.auth_version


@pytest.mark.django_db
def test_user_admin_login_as_requires_active_superuser():
    """Deny impersonation to an account without active superuser authority."""
    factory = RequestFactory()
    regular_user = User.objects.create_user(email='user@example.com', password='pass1234')
    target_user = User.objects.create_user(email='target@example.com', password='pass1234')
    request = factory.get('/admin/')
    request.user = regular_user

    admin = VersionaUserAdmin(User, admin_site)

    with pytest.raises(PermissionDenied) as exc_info:
        admin.login_as_user_view(request, target_user.id)

    assert exc_info.type is PermissionDenied


@pytest.mark.django_db
@pytest.mark.parametrize('build_target', [
    pytest.param(
        lambda: User.objects.create_superuser(email='target@example.com', password='pass1234'),
        id='superuser',
    ),
    pytest.param(
        lambda: User.objects.create_user(
            email='target@example.com', password='pass1234', is_active=False,
        ),
        id='inactive',
    ),
])
def test_user_admin_login_as_blocks_ineligible_target(build_target):
    """Deny token issuance for inactive or superuser impersonation targets."""
    admin_user = User.objects.create_superuser(email='admin@example.com', password='pass1234')
    target_user = build_target()
    request = _request_with_messages(admin_user)

    admin = VersionaUserAdmin(User, admin_site)
    response = admin.login_as_user_view(request, target_user.id)

    assert response.status_code == 302
    assert 'access=' not in response['Location']
    assert f'/user/{target_user.id}/change/' in response['Location']
