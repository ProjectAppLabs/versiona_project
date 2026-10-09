"""
Authentication views for user sign up, sign in, and password management.
"""
import logging

from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenObtainSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.contrib.auth.models import update_last_login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

import requests

from accounts.models import PasswordCode
from accounts.throttles import AuthThrottle
from accounts.utils.auth_utils import (
    generate_auth_tokens, 
    send_password_reset_code
)
from accounts.views.captcha_views import verify_recaptcha

User = get_user_model()

logger = logging.getLogger(__name__)


def _password_validation_error(password, user):
    """Return configured password policy errors in the API's existing shape."""
    if not isinstance(password, str):
        return 'Password must be a string'
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return ' '.join(exc.messages)
    return None


def _login_admission(user):
    """Require an active account and its second factor before issuing tokens."""
    if not user.is_active:
        return Response({'error': 'Account is inactive'}, status=status.HTTP_401_UNAUTHORIZED)
    if user.totp_enabled_at:
        from accounts.twofactor import issue_challenge

        return Response(
            {'requires_2fa': True, 'challenge': issue_challenge(user)},
            status=status.HTTP_202_ACCEPTED,
        )
    return None


class TokenObtainPairWithAdmissionView(TokenObtainPairView):
    """Preserve the JWT alias while admitting both authentication factors."""

    serializer_class = TokenObtainSerializer
    throttle_classes = [AuthThrottle]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.user
        admission = _login_admission(user)
        if admission is not None:
            return admission

        # Pair validation mints a token, so only use it after admission.
        refresh = TokenObtainPairSerializer.get_token(user)
        if jwt_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, user)
        return Response({'refresh': str(refresh), 'access': str(refresh.access_token)})


class AuthTokenRefreshView(TokenRefreshView):
    """Refresh participates in the same attempt budget as initial admission."""

    throttle_classes = [AuthThrottle]


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def sign_up(request):
    """
    User registration endpoint.
    
    Expected data:
    - email: str
    - password: str
    - first_name: str (optional)
    - last_name: str (optional)
    """
    captcha_token = request.data.get('captcha_token', '')
    if not verify_recaptcha(captcha_token):
        return Response(
            {'captcha_token': ['reCAPTCHA verification failed.']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password')
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    
    if not email or not password:
        return Response(
            {'error': 'Email and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if isinstance(password, str) and len(password) < 8:
        return Response(
            {'error': 'Password must be at least 8 characters'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if User.objects.filter(email=email).exists():
        return Response(
            {'error': 'User with this email already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    password_error = _password_validation_error(
        password,
        User(email=email, first_name=first_name, last_name=last_name),
    )
    if password_error:
        return Response({'error': password_error}, status=status.HTTP_400_BAD_REQUEST)
    
    # Create user
    user = User.objects.create(
        email=email,
        first_name=first_name,
        last_name=last_name,
        password=make_password(password),
        is_active=True
    )

    # Every user owns a personal organization from day one (A1)
    from orgs.services import ensure_personal_org
    ensure_personal_org(user)

    # Generate tokens
    tokens = generate_auth_tokens(user)

    return Response(tokens, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def sign_in(request):
    """
    User sign in endpoint.
    
    Expected data:
    - email: str
    - password: str
    """
    captcha_token = request.data.get('captcha_token', '')
    if not verify_recaptcha(captcha_token):
        return Response(
            {'captcha_token': ['reCAPTCHA verification failed.']},
            status=status.HTTP_400_BAD_REQUEST,
        )

    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password')
    
    if not email or not password:
        return Response(
            {'error': 'Email and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    if not check_password(password, user.password):
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    admission = _login_admission(user)
    if admission is not None:
        return admission

    # Generate tokens
    tokens = generate_auth_tokens(user)
    
    return Response(tokens, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def google_login(request):
    """
    Google OAuth login endpoint.

    Expected data: credential (or id_token).
    Email and name hints are used only by the DEBUG transport fallback.
    """
    credential = request.data.get('credential') or request.data.get('id_token')

    if not credential:
        return Response({'error': 'Google credential is required'}, status=status.HTTP_400_BAD_REQUEST)

    allowed_auds = [
        value.strip()
        for value in (settings.GOOGLE_OAUTH_CLIENT_ID or '').split(',')
        if value.strip()
    ]
    if not allowed_auds and not settings.DEBUG:
        return Response({'error': 'Invalid Google client'}, status=status.HTTP_401_UNAUTHORIZED)

    payload = None
    try:
        tokeninfo = requests.get(
            'https://oauth2.googleapis.com/tokeninfo',
            params={'id_token': credential},
            timeout=5,
        )
        if tokeninfo.status_code == 200:
            try:
                payload = tokeninfo.json()
            except ValueError:
                return Response({'error': 'Invalid Google credential'}, status=status.HTTP_401_UNAUTHORIZED)

            if not isinstance(payload, dict):
                return Response({'error': 'Invalid Google credential'}, status=status.HTTP_401_UNAUTHORIZED)

            aud = payload.get('aud')
            if not isinstance(aud, str) or not aud.strip() or aud not in allowed_auds:
                return Response({'error': 'Invalid Google client'}, status=status.HTTP_401_UNAUTHORIZED)

            token_email = payload.get('email')
            email_verified = payload.get('email_verified')
            if (
                not isinstance(token_email, str)
                or not token_email.strip()
                or not (email_verified is True or email_verified == 'true')
            ):
                return Response({'error': 'Invalid Google credential'}, status=status.HTTP_401_UNAUTHORIZED)

            token_given = payload.get('given_name', '')
            token_family = payload.get('family_name', '')
            if not isinstance(token_given, str) or not isinstance(token_family, str):
                return Response({'error': 'Invalid Google credential'}, status=status.HTTP_401_UNAUTHORIZED)

            email = token_email.strip().lower()
            given_name = token_given.strip()
            family_name = token_family.strip()
        else:
            logger.warning('Google tokeninfo rejected credential: status=%s', tokeninfo.status_code)
    except requests.RequestException:
        logger.warning('Google token validation transport failed')

    if payload is None:
        if not settings.DEBUG:
            return Response({'error': 'Invalid Google credential'}, status=status.HTTP_401_UNAUTHORIZED)

        # Invalid claims returned with HTTP 200 never reach this fallback.
        email = request.data.get('email', '').strip().lower()
        given_name = request.data.get('given_name', '').strip()
        family_name = request.data.get('family_name', '').strip()
    
    if not email:
        return Response(
            {'error': 'Email is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get or create user
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            'first_name': given_name,
            'last_name': family_name,
            'is_active': True,
        }
    )

    admission = _login_admission(user)
    if admission is not None:
        return admission

    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    
    # Update names if user exists but doesn't have them
    if not created:
        if not user.first_name and given_name:
            user.first_name = given_name
        if not user.last_name and family_name:
            user.last_name = family_name
        if user.first_name or user.last_name:
            user.save()

    # Every user owns a personal organization from day one (A1); idempotent
    from orgs.services import ensure_personal_org
    ensure_personal_org(user)

    # Generate tokens
    tokens = generate_auth_tokens(user)
    tokens['created'] = created
    tokens['google_validated'] = payload is not None

    return Response(tokens, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def send_passcode(request):
    """
    Send password reset code to user's email.
    
    Expected data:
    - email: str
    """
    email = request.data.get('email', '').strip().lower()
    
    if not email:
        return Response(
            {'error': 'Email is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        # Don't reveal if user exists
        return Response(
            {'message': 'If the email exists, a code has been sent'},
            status=status.HTTP_200_OK
        )
    
    # Generate and save code
    password_code = PasswordCode.generate_code(user)
    
    # Send email
    success = send_password_reset_code(user, password_code.code)
    
    if not success:
        return Response(
            {'error': 'Failed to send email'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    return Response(
        {'message': 'Code sent successfully'},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def verify_passcode_and_reset_password(request):
    """
    Verify passcode and reset password.
    
    Expected data:
    - email: str
    - code: str
    - new_password: str
    """
    email = request.data.get('email', '').strip().lower()
    code = request.data.get('code', '').strip()
    new_password = request.data.get('new_password')
    
    if not email or not code or not new_password:
        return Response(
            {'error': 'Email, code, and new password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    with transaction.atomic():
        try:
            user = User.objects.select_for_update().get(email=email)
        except User.DoesNotExist:
            return Response(
                {'error': 'Invalid email or code'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Serialize attempts for this user and re-read the code under its own
        # lock. Password validation must succeed before either row changes.
        try:
            password_code = user.password_codes.select_for_update().filter(
                code=code,
                used=False,
            ).first()
            if password_code and not password_code.is_valid():
                password_code = None
        except Exception:
            return Response(
                {'error': 'Invalid or expired code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if password_code is None:
            # A wrong or expired code burns every pending code of this account,
            # under the user lock: each issued code admits one failed guess.
            # The bound lives in the database, so it holds whatever IP or
            # worker process the attempts come from.
            user.password_codes.filter(used=False).update(used=True)
            return Response(
                {'error': 'Invalid or expired code'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        password_error = _password_validation_error(new_password, user)
        if password_error:
            return Response({'error': password_error}, status=status.HTTP_400_BAD_REQUEST)

        user.password = make_password(new_password)
        user.save(update_fields=['password'])
        password_code.used = True
        password_code.save(update_fields=['used'])
    
    return Response(
        {'message': 'Password reset successfully'},
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_password(request):
    """
    Update user password (requires authentication).
    
    Expected data:
    - current_password: str
    - new_password: str
    """
    current_password = request.data.get('current_password')
    new_password = request.data.get('new_password')
    
    if not current_password or not new_password:
        return Response(
            {'error': 'Current password and new password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    user = request.user
    
    if not check_password(current_password, user.password):
        return Response(
            {'error': 'Current password is incorrect'},
            status=status.HTTP_400_BAD_REQUEST
        )

    password_error = _password_validation_error(new_password, user)
    if password_error:
        return Response({'error': password_error}, status=status.HTTP_400_BAD_REQUEST)
    
    user.password = make_password(new_password)
    user.save()
    
    return Response(
        {'message': 'Password updated successfully'},
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def validate_token(request):
    """
    Validate JWT token and return user info.
    """
    user = request.user
    return Response({
        'valid': True,
        'user': {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'is_staff': user.is_staff,
        }
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def sign_in_2fa(request):
    """Second step: challenge + TOTP (or backup) code → tokens."""
    from accounts.twofactor import resolve_challenge, verify_code
    from documents.services.version_service import DomainError

    try:
        user = resolve_challenge((request.data or {}).get('challenge', ''))
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    if not verify_code(user, (request.data or {}).get('code', '')):
        return Response({'error': 'Código incorrecto.'}, status=status.HTTP_401_UNAUTHORIZED)
    return Response(generate_auth_tokens(user), status=status.HTTP_200_OK)
