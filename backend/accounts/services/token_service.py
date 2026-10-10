"""Session epochs shared by every JWT admission and credential rotation."""
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


def version_matches(payload, user):
    # Pre-deployment tokens remain usable only until this account rotates.
    version = payload.get('auth_version', 0)
    return type(version) is int and version >= 0 and version == user.auth_version


def mint_token_pair(user):
    # Never reload the epoch here: it belongs to the credentials authenticated
    # by the caller. Concurrent rotations make this pair stale, never elevated.
    refresh = RefreshToken.for_user(user)
    refresh['auth_version'] = user.auth_version
    OutstandingToken.objects.filter(jti=refresh['jti']).update(token=str(refresh))
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


def rotate_credentials(user):
    """Caller holds the user row lock and saves its credential changes."""
    user.auth_version += 1
    for token in OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now()):
        BlacklistedToken.objects.get_or_create(token=token)
