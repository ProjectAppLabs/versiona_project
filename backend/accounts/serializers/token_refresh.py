"""Refresh rotation is serialized with password and identity changes."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from accounts.services.token_service import version_matches


class VersionedTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = self.token_class(attrs['refresh'])
        with transaction.atomic():
            try:
                user = get_user_model().objects.select_for_update().get(
                    **{api_settings.USER_ID_FIELD: refresh[api_settings.USER_ID_CLAIM]}
                )
            except (get_user_model().DoesNotExist, KeyError, TypeError, ValueError):
                raise AuthenticationFailed('La sesión ha vencido.', code='session_revoked')
            if not user.is_active or not version_matches(refresh, user):
                raise AuthenticationFailed('La sesión ha vencido.', code='session_revoked')
            # Also stamp compatible legacy tokens when they rotate.
            refresh['auth_version'] = user.auth_version
            return super().validate({'refresh': str(refresh)})
