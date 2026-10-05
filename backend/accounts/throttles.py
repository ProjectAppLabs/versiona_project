"""One auth attempt budget per IP across all authentication entrypoints."""

from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle


class AuthThrottle(SimpleRateThrottle):
    scope = 'auth'

    def get_rate(self):
        """Read the current rate, including explicit test-setting overrides."""
        return api_settings.DEFAULT_THROTTLE_RATES[self.scope]

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
