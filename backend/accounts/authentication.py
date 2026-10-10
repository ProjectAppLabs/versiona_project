"""Reject access tokens immediately after credential rotation."""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from accounts.services.token_service import version_matches


class VersionedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not version_matches(validated_token, user):
            raise AuthenticationFailed('La sesión ha vencido. Vuelve a entrar.', code='session_revoked')
        return user
