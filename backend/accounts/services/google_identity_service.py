"""Verified Google identities and email-recovery admission for explicit linking."""
import time
from dataclasses import dataclass

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import APIException

from accounts.services.token_service import rotate_credentials, version_matches

TICKET_SALT = 'versiona.google-link.recovery'
TICKET_MAX_AGE = 15 * 60
TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'


class GoogleIdentityError(APIException):
    def __init__(self, message, status_code=400, code='google_credential_invalid'):
        self.status_code = status_code
        self.detail = {'error': message, 'code': code}


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    given_name: str
    family_name: str


def verify_google_identity(credential):
    if not isinstance(credential, str) or not credential:
        raise GoogleIdentityError('Google credential is required')
    audiences = {value.strip() for value in (settings.GOOGLE_OAUTH_CLIENT_ID or '').split(',') if value.strip()}
    if not audiences:
        raise GoogleIdentityError('Invalid Google client', 401)
    try:
        response = requests.get(TOKENINFO_URL, params={'id_token': credential}, timeout=5)
        if response.status_code != 200:
            raise GoogleIdentityError('Invalid Google credential', 401)
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise GoogleIdentityError('Invalid Google credential', 401)
    if not isinstance(payload, dict):
        raise GoogleIdentityError('Invalid Google credential', 401)
    if not isinstance(payload.get('aud'), str) or payload['aud'] not in audiences:
        raise GoogleIdentityError('Invalid Google client', 401)
    subject, email = payload.get('sub'), payload.get('email')
    given, family = payload.get('given_name', ''), payload.get('family_name', '')
    try:
        expires = int(payload.get('exp', 0))
    except (TypeError, ValueError, OverflowError):
        expires = 0
    if (
        not isinstance(subject, str) or not subject.strip() or subject != subject.strip() or len(subject) > 255
        or not isinstance(email, str) or not email.strip() or len(email.strip()) > 254
        or not (payload.get('email_verified') is True or payload.get('email_verified') == 'true')
        or payload.get('iss') not in ('accounts.google.com', 'https://accounts.google.com')
        or expires <= time.time()
        or not isinstance(given, str) or not isinstance(family, str)
    ):
        raise GoogleIdentityError('Invalid Google credential', 401)
    return GoogleIdentity(subject, email.strip().lower(), given.strip()[:150], family.strip()[:150])


def issue_link_ticket(user):
    return signing.dumps({'purpose': 'google-link', 'user': user.pk, 'auth_version': user.auth_version}, salt=TICKET_SALT)


def _valid_ticket(ticket, user):
    if not isinstance(ticket, str) or not ticket:
        return False
    try:
        payload = signing.loads(ticket, salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except (signing.BadSignature, TypeError, ValueError):
        return False
    return (isinstance(payload, dict) and payload.get('purpose') == 'google-link'
            and type(payload.get('user')) is int and payload['user'] == user.pk
            and type(payload.get('auth_version')) is int and version_matches(payload, user))



def _email_conflict(existing):
    if existing is not None and existing.google_subject:
        return GoogleIdentityError('Este correo ya tiene otra identidad de Google vinculada.', 409, 'google_identity_conflict')
    return GoogleIdentityError('Recupera tu cuenta por correo y conecta Google en Configuración → Seguridad.', 409, 'google_link_required')


def google_account(identity):
    """Never use a matching email to authenticate or modify an existing user."""
    User = get_user_model()
    with transaction.atomic():
        user = User.objects.filter(google_subject=identity.subject).first()
        if user is not None:
            return user, False
        existing = User.objects.filter(email=identity.email).only('google_subject').first()
        if existing is not None:
            raise _email_conflict(existing)
        try:
            with transaction.atomic():
                user = User(email=identity.email, google_subject=identity.subject,
                            first_name=identity.given_name, last_name=identity.family_name)
                user.set_unusable_password()
                user.save()
        except IntegrityError:
            # Concurrent first admission can only converge on the same subject.
            user = User.objects.filter(google_subject=identity.subject).first()
            if user is not None:
                return user, False
            raise _email_conflict(User.objects.filter(email=identity.email).only('google_subject').first())
        from orgs.services import ensure_personal_org
        ensure_personal_org(user)
        return user, True


def link_google(user, auth_payload, data, identity):
    """The external credential has been verified before taking this row lock."""
    from accounts.twofactor import verify_code
    from accounts.utils.auth_utils import generate_auth_tokens

    current, replacement = data.get('current_password'), data.get('new_password')
    if not isinstance(current, str) or not current or not isinstance(replacement, str) or not replacement:
        raise GoogleIdentityError('Indica tu contraseña actual y una contraseña nueva.')
    try:
        with transaction.atomic():
            locked = get_user_model().objects.select_for_update().get(pk=user.pk)
            # Force-authentication test clients have no JWT; real requests do.
            if not locked.is_active or not version_matches(auth_payload or {'auth_version': user.auth_version}, locked):
                raise GoogleIdentityError('La sesión ha vencido. Vuelve a entrar.', 403, 'reauthentication_required')
            if not _valid_ticket(data.get('google_link_ticket'), locked) or not locked.check_password(current):
                raise GoogleIdentityError('Recupera tu cuenta por correo y vuelve a entrar para conectar Google.', 403, 'reauthentication_required')
            if locked.google_subject or identity.email != locked.email.strip().lower():
                raise GoogleIdentityError('La identidad de Google no corresponde a esta cuenta o ya está vinculada.', 409, 'google_identity_conflict')
            if get_user_model().objects.filter(google_subject=identity.subject).exclude(pk=locked.pk).exists():
                raise GoogleIdentityError('Esta identidad de Google ya está vinculada.', 409, 'google_identity_conflict')
            if replacement == current or locked.check_password(replacement):
                raise GoogleIdentityError('La contraseña nueva debe ser distinta.')
            try:
                validate_password(replacement, user=locked)
            except ValidationError as exc:
                raise GoogleIdentityError(' '.join(exc.messages))
            if locked.totp_enabled_at and not verify_code(locked, data.get('code', '')):
                raise GoogleIdentityError('Código de segundo factor incorrecto.', 403, 'reauthentication_required')
            locked.google_subject = identity.subject
            locked.set_password(replacement)
            rotate_credentials(locked)
            locked.save(update_fields=['google_subject', 'password', 'auth_version'])
            return generate_auth_tokens(locked)
    except IntegrityError:
        raise GoogleIdentityError('Esta identidad de Google ya está vinculada.', 409, 'google_identity_conflict')
