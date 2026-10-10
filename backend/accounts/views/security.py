"""A3 endpoints: 2FA lifecycle + active sessions."""

from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from accounts import twofactor
from accounts.throttles import AuthThrottle
from documents.services.version_service import DomainError


@api_view(['GET'])
def my_security(request):
    return Response({
        'google_linked': bool(request.user.google_subject),
        'has_usable_password': request.user.has_usable_password(),
        'totp_enabled': bool(request.user.totp_enabled_at),
        'totp_enabled_at': request.user.totp_enabled_at,
        'backup_codes_left': len(request.user.totp_backup_codes or []),
        'sso': 'DECISIÓN PENDIENTE',  # corporate IdP required (docs/audit/02 §4)
    })


@api_view(['POST'])
def twofa_setup(request):
    try:
        return Response(twofactor.setup(request.user))
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)


@api_view(['POST'])
@throttle_classes([AuthThrottle])
def twofa_enable(request):
    try:
        backup_codes = twofactor.enable(request.user, (request.data or {}).get('code', ''))
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'backup_codes': backup_codes}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@throttle_classes([AuthThrottle])
def twofa_disable(request):
    try:
        twofactor.disable(request.user, (request.data or {}).get('code', ''))
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'totp_enabled': False})


@api_view(['GET'])
def my_sessions(request):
    return Response({'results': twofactor.list_sessions(request.user)})


@api_view(['POST'])
def session_revoke(request, session_id):
    try:
        twofactor.revoke_session(request.user, session_id)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'revoked': session_id})


@api_view(['POST'])
def sessions_revoke_others(request):
    revoked = twofactor.revoke_other_sessions(
        request.user, (request.data or {}).get('refresh')
    )
    return Response({'revoked': revoked})


@api_view(['POST'])
@throttle_classes([AuthThrottle])
def google_link(request):
    from accounts.services.google_identity_service import GoogleIdentityError, verify_google_identity, link_google

    try:
        # Network I/O happens before the service takes the account row lock.
        identity = verify_google_identity((request.data or {}).get('credential'))
        tokens = link_google(request.user, request.auth, request.data, identity)
    except GoogleIdentityError as exc:
        # Linking has a uniform input error status; it never authenticates.
        return Response(exc.detail, status=400 if exc.status_code == 401 else exc.status_code)
    return Response(tokens, status=status.HTTP_201_CREATED)
