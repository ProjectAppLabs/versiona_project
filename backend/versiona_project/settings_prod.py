"""
Production settings for versiona_project.

Usage: DJANGO_SETTINGS_MODULE=versiona_project.settings_prod

This file is imported AFTER settings.py (base). All shared configuration
lives in settings.py; this file only contains production overrides and
validations.
"""

import os

from .db import build_db_config
from .settings import BASE_DIR  # noqa: F401
from .settings import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# Core safety: DEBUG is always False in production
# ---------------------------------------------------------------------------
DEBUG = False

# ---------------------------------------------------------------------------
# Required environment variables — fail fast if missing
# ---------------------------------------------------------------------------
if not os.getenv('DJANGO_SECRET_KEY'):
    raise ValueError("DJANGO_SECRET_KEY is required in production")

if not os.getenv('DJANGO_ALLOWED_HOSTS'):
    raise ValueError("DJANGO_ALLOWED_HOSTS is required in production")

# ---------------------------------------------------------------------------
# Security hardening
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# The deployed /api/ route goes through one nginx proxy into the Unix socket.
# Ignore any X-Forwarded-For prefix supplied by the visitor when throttling.
REST_FRAMEWORK = {**REST_FRAMEWORK, 'NUM_PROXIES': 1}  # noqa: F405

# ---------------------------------------------------------------------------
# Database — MySQL 8 (production). Same builder as the base settings, so the
# driver OPTIONS cannot drift between the two files.
# ---------------------------------------------------------------------------
DATABASES = {'default': build_db_config(BASE_DIR)}

# ---------------------------------------------------------------------------
# Production email — require SMTP backend
# ---------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# ---------------------------------------------------------------------------
# Production logging — add file handler
# ---------------------------------------------------------------------------
LOGGING['handlers']['file'] = {  # noqa: F405
    'level': 'WARNING',
    'class': 'logging.FileHandler',
    'filename': BASE_DIR / 'logs' / 'django.log',
    'formatter': 'verbose',
}
LOGGING['loggers']['django']['handlers'].append('file')  # noqa: F405
