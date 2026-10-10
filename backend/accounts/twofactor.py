"""
A3 — TOTP two-factor auth + active-session management (docs/audit/03 A3).

2FA: pyotp secrets, backup codes stored as sha256 (shown ONCE), and a signed
short-lived challenge between the password step and the code step. Corporate
SSO stays a DECISIÓN PENDIENTE (needs the operator's IdP).

Sessions: every refresh token issued is an OutstandingToken (simplejwt
blacklist app); revoking a session blacklists its refresh token.
"""

import base64
import hashlib
import io
import secrets

import pyotp
import qrcode
from django.core import signing
from django.db import transaction
from django.utils import timezone

from documents.services.version_service import DomainError

CHALLENGE_SALT = 'versiona.2fa.challenge'
CHALLENGE_MAX_AGE = 300  # seconds
BACKUP_CODE_COUNT = 8


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().replace('-', '').lower().encode()).hexdigest()


def setup(user) -> dict:
    """Start (or restart) enrolment: a fresh secret, NOT yet enabled."""
    if user.totp_enabled_at:
        raise DomainError('El 2FA ya está activo. Desactívalo antes de re-enrolar.', 409)
    secret = pyotp.random_base32()
    user.totp_secret = secret
    user.save(update_fields=['totp_secret'])
    otpauth_url = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name='Versiona'
    )
    image = qrcode.make(otpauth_url, box_size=6, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    qr_data_uri = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    return {'secret': secret, 'otpauth_url': otpauth_url, 'qr': qr_data_uri}


def enable(user, code: str) -> list[str]:
    """Verify the first code and turn 2FA on. Returns the backup codes —
    the only time they exist in plaintext."""
    if user.totp_enabled_at:
        raise DomainError('El 2FA ya está activo.', 409)
    if not user.totp_secret:
        raise DomainError('Primero genera el secreto (setup).', 409)
    if not pyotp.TOTP(user.totp_secret).verify(code.strip(), valid_window=1):
        raise DomainError('Código incorrecto. Verifica la hora de tu dispositivo.', 400)
    backup_codes = [
        f'{secrets.token_hex(2)}-{secrets.token_hex(2)}' for _ in range(BACKUP_CODE_COUNT)
    ]
    user.totp_backup_codes = [_hash_code(code) for code in backup_codes]
    user.totp_enabled_at = timezone.now()
    user.save(update_fields=['totp_backup_codes', 'totp_enabled_at'])
    return backup_codes


def _consume_backup_code(user, code: str) -> bool:
    hashed = _hash_code(code)
    with transaction.atomic():
        # Requests can hold different instances of the same user. Only the
        # locked, current row can decide whether a code is still available.
        current_user = type(user).objects.select_for_update().get(pk=user.pk)
        codes = list(current_user.totp_backup_codes or [])
        if hashed not in codes:
            return False
        codes.remove(hashed)
        current_user.totp_backup_codes = codes
        current_user.save(update_fields=['totp_backup_codes'])
    user.totp_backup_codes = codes
    return True


def verify_code(user, code: str) -> bool:
    """A TOTP code or an unused backup code."""
    if not isinstance(code, str):
        return False
    code = code.strip()
    if not code:
        return False
    if user.totp_secret and pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        return True
    return _consume_backup_code(user, code)


def disable(user, code: str):
    if not user.totp_enabled_at:
        raise DomainError('El 2FA no está activo.', 409)
    if not verify_code(user, code):
        raise DomainError('Código incorrecto.', 400)
    user.totp_secret = ''
    user.totp_backup_codes = []
    user.totp_enabled_at = None
    user.save(update_fields=['totp_secret', 'totp_backup_codes', 'totp_enabled_at'])


def issue_challenge(user) -> str:
    """Signed, short-lived proof that the first authentication step passed."""
    return signing.dumps({'user': user.pk, 'auth_version': user.auth_version}, salt=CHALLENGE_SALT)


def resolve_challenge(challenge: str):
    from django.contrib.auth import get_user_model

    invalid_challenge = 'Desafío inválido o vencido.'
    if not isinstance(challenge, str) or not challenge:
        raise DomainError(invalid_challenge, 401)
    try:
        payload = signing.loads(challenge, salt=CHALLENGE_SALT, max_age=CHALLENGE_MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError) as exc:
        raise DomainError(invalid_challenge, 401) from exc
    if not isinstance(payload, dict) or type(payload.get('user')) is not int:
        raise DomainError(invalid_challenge, 401)

    user_model = get_user_model()
    try:
        user = user_model.objects.get(pk=payload['user'])
    except (user_model.DoesNotExist, ValueError, TypeError, OverflowError) as exc:
        raise DomainError(invalid_challenge, 401) from exc
    from accounts.services.token_service import version_matches

    if not user.is_active or not user.totp_enabled_at or not version_matches(payload, user):
        raise DomainError(invalid_challenge, 401)
    return user


# ── Active sessions (refresh tokens) ───────────────────────────────────────


def list_sessions(user) -> list[dict]:
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    blacklisted = set(
        BlacklistedToken.objects.filter(token__user=user).values_list('token_id', flat=True)
    )
    sessions = []
    for token in OutstandingToken.objects.filter(
        user=user, expires_at__gt=timezone.now()
    ).order_by('-created_at'):
        if token.id in blacklisted:
            continue
        sessions.append({
            'id': token.id,
            'jti': token.jti[:8],
            'created_at': token.created_at,
            'expires_at': token.expires_at,
        })
    return sessions


def revoke_session(user, session_id: int):
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    token = OutstandingToken.objects.filter(user=user, id=session_id).first()
    if token is None:
        raise DomainError('Sesión no encontrada.', 404)
    BlacklistedToken.objects.get_or_create(token=token)


def revoke_other_sessions(user, keep_refresh: str | None) -> int:
    """Blacklist every session except the one whose refresh token is passed."""
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )
    from rest_framework_simplejwt.tokens import RefreshToken

    keep_jti = None
    if keep_refresh:
        try:
            keep_jti = RefreshToken(keep_refresh)['jti']
        except Exception:
            keep_jti = None
    revoked = 0
    for token in OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now()):
        if keep_jti and token.jti == keep_jti:
            continue
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            revoked += 1
    return revoked
