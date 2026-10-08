"""
Django settings for Versiona (versiona_project).

Base settings shared by all environments. Environment-specific overrides live
in settings_dev.py and settings_prod.py (selected via DJANGO_SETTINGS_MODULE).
"""

import os
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .db import build_db_config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

load_dotenv(BASE_DIR / '.env')

# Environment detection
DJANGO_ENV = os.getenv('DJANGO_ENV', 'development')
IS_PRODUCTION = DJANGO_ENV == 'production'
ENABLE_SILK = os.getenv('ENABLE_SILK', 'false').lower() in {'1', 'true', 'yes', 'on'}

# Fleet staging contract: a staging deployment is production-grade in every way
# EXCEPT that it does not take its own backups and does not e-mail performance
# reports. Both default to on so a production deployment needs no extra env.
BACKUPS_ENABLED = os.getenv('BACKUPS_ENABLED', 'true').lower() in {'1', 'true', 'yes', 'on'}
ENABLE_SLOW_QUERIES_REPORT = os.getenv(
    'ENABLE_SLOW_QUERIES_REPORT', 'true'
).lower() in {'1', 'true', 'yes', 'on'}

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'change-me')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() in {'1', 'true', 'yes', 'on'}

ALLOWED_HOSTS = [h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_cleanup.apps.CleanupConfig',
    'dbbackup',
    # Versiona bounded contexts (docs/plan/03 §2)
    'core',
    'accounts',
    'orgs',
    'projects',
    'documents',
    'reviews',
    'observations',
    'checks',
    'comparisons',
    'engine',
    'notifications',
    'billing',
    'audit',
    'public_tools',
]

if ENABLE_SILK:
    INSTALLED_APPS.append('silk')

AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = []
if ENABLE_SILK:
    MIDDLEWARE.append('silk.middleware.SilkyMiddleware')
MIDDLEWARE += [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        'DJANGO_CORS_ALLOWED_ORIGINS',
        'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000',
    ).split(',') if o.strip()
]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'accept-language',
    'authorization',
    'content-type',
    'origin',
    'x-csrftoken',
    'x-requested-with',
    'x-currency',
]

CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv(
        'DJANGO_CSRF_TRUSTED_ORIGINS',
        'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000',
    ).split(',') if o.strip()
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_THROTTLE_RATES': {
        'auth': os.getenv('THROTTLE_AUTH', '5/min'),
        'upload': os.getenv('THROTTLE_UPLOAD', '20/hour'),
        'webhook': os.getenv('THROTTLE_WEBHOOK', '60/min'),
        'public': os.getenv('THROTTLE_PUBLIC', '30/min'),
        'public_compare': os.getenv('THROTTLE_PUBLIC_COMPARE', '10/hour'),
        'public_compare_daily': os.getenv('THROTTLE_PUBLIC_COMPARE_DAILY', '30/day'),
        'public_compare_status': os.getenv('THROTTLE_PUBLIC_COMPARE_STATUS', '60/min'),
    },
}

GOOGLE_OAUTH_CLIENT_ID = os.getenv('DJANGO_GOOGLE_CLIENT_ID', '').strip()

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=int(os.getenv('DJANGO_JWT_ACCESS_MINUTES', '15'))
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        days=int(os.getenv('DJANGO_JWT_REFRESH_DAYS', '7'))
    ),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

ROOT_URLCONF = 'versiona_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'versiona_project.wsgi.application'


# Database — MySQL 8
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {'default': build_db_config(BASE_DIR)}


# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# TTL of a signed object URL: the filesystem backend bakes it into the token's
# `exp`.
MEDIA_SIGNED_URL_TTL_SECONDS = int(os.getenv('MEDIA_SIGNED_URL_TTL_SECONDS', '300'))

# Filesystem object storage for domain media — the only backend. The S3/MinIO
# one was removed on 2026-08-02: no environment configured a bucket, so it ran
# nowhere and nothing covered it.
# The root sits OUTSIDE MEDIA_ROOT on purpose: urls.py serves MEDIA_ROOT
# unsigned under DEBUG and nginx aliases /media/ to it, so an object placed
# there would be readable by guessing its path. A system check enforces this.
OBJECT_STORAGE_ROOT = os.getenv('OBJECT_STORAGE_ROOT', os.path.join(BASE_DIR, 'var', 'objects'))
OBJECT_STORAGE_DIR_MODE = 0o750
OBJECT_STORAGE_FILE_MODE = 0o640
# Set to nginx's `internal` location (e.g. /__objects_internal) to hand delivery
# off with X-Accel-Redirect. Empty = stream from Django, which is what dev and
# the test client need.
OBJECT_STORAGE_SENDFILE_ROOT = os.getenv('OBJECT_STORAGE_SENDFILE_ROOT', '')
# Signed URLs are root-relative by default, so they stay correct on every
# hostname the app answers on. Set this only to force an absolute origin.
OBJECT_STORAGE_PUBLIC_ORIGIN = os.getenv('OBJECT_STORAGE_PUBLIC_ORIGIN', '').rstrip('/')

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
    'dbbackup': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'OPTIONS': {
            'location': os.getenv('BACKUP_STORAGE_PATH', '/var/backups/versiona'),
        },
    },
}

# Email configuration (for password reset codes)
EMAIL_HOST = os.getenv('DJANGO_EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('DJANGO_EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('DJANGO_EMAIL_USE_TLS', 'true').lower() in {'1', 'true', 'yes', 'on'}
try:
    EMAIL_TIMEOUT = int(os.getenv('DJANGO_EMAIL_TIMEOUT', '5'))
except ValueError as exc:
    raise ImproperlyConfigured('DJANGO_EMAIL_TIMEOUT debe ser un entero positivo.') from exc
if EMAIL_TIMEOUT <= 0:
    raise ImproperlyConfigured('DJANGO_EMAIL_TIMEOUT debe ser un entero positivo.')
EMAIL_HOST_USER = os.getenv('DJANGO_EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('DJANGO_EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DJANGO_DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
EMAIL_BACKEND = os.getenv('DJANGO_EMAIL_BACKEND') or (
    'django.core.mail.backends.smtp.EmailBackend'
    if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD
    else 'django.core.mail.backends.console.EmailBackend'
)

# ---------------------------------------------------------------------------
# Google reCAPTCHA
# ---------------------------------------------------------------------------
RECAPTCHA_SITE_KEY = os.getenv('RECAPTCHA_SITE_KEY', '')
RECAPTCHA_SECRET_KEY = os.getenv('RECAPTCHA_SECRET_KEY', '')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(exist_ok=True)

LOG_LEVEL = os.getenv('DJANGO_LOG_LEVEL', 'INFO')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'backup_file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGS_DIR / 'backups.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 3,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'backups': {
            'handlers': ['backup_file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ---------------------------------------------------------------------------
# Backups (django-dbbackup)
# Storage is configured via STORAGES['dbbackup'] above (FileSystemStorage).
# ---------------------------------------------------------------------------
DBBACKUP_COMPRESS = True
DBBACKUP_FILENAME_TEMPLATE = '{datetime}.sql'
DBBACKUP_MEDIA_FILENAME_TEMPLATE = '{datetime}.tar'
DBBACKUP_CLEANUP_KEEP = 4
DBBACKUP_CLEANUP_KEEP_MEDIA = 4

# ---------------------------------------------------------------------------
# Task Queue (Celery) — broker and result backend on Redis.
# Queues (docs/plan/05 §7): default (domain), engine_light, engine_heavy.
# In non-production environments tasks run eagerly by default (mirrors the
# template's Huey immediate mode); export CELERY_TASK_ALWAYS_EAGER=0 to
# exercise a real worker in development.
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv(
    'CELERY_TASK_ALWAYS_EAGER', 'false' if IS_PRODUCTION else 'true'
).lower() in {'1', 'true', 'yes', 'on'}
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_DEFAULT_QUEUE = 'default'

# Operational periodic tasks inherited from the template (formerly Huey).
CELERY_BEAT_SCHEDULE = {
    'recover-pending-analysis-minute': {
        'task': 'engine.tasks.recover_pending_analysis',
        'schedule': 60.0,
        'options': {'queue': 'default', 'expires': 60},
    },
    'scheduled-backup-weekly': {
        'task': 'versiona_project.tasks.scheduled_backup',
        'schedule': crontab(day_of_week='0', hour='3', minute='0'),
    },
    'silk-garbage-collection-daily': {
        'task': 'versiona_project.tasks.silk_garbage_collection',
        'schedule': crontab(hour='4', minute='0'),
    },
    'weekly-slow-queries-report': {
        'task': 'versiona_project.tasks.weekly_slow_queries_report',
        'schedule': crontab(day_of_week='1', hour='8', minute='0'),
    },
    'silk-reports-cleanup-monthly': {
        'task': 'versiona_project.tasks.silk_reports_cleanup',
        'schedule': crontab(day_of_month='1', hour='5', minute='0'),
    },
    'purge-trashed-daily': {
        'task': 'versiona_project.tasks.purge_trashed',
        'schedule': crontab(hour='2', minute='30'),
    },
    # F1 trials: expiry bookkeeping + owner notices (~08:00 America/Bogota).
    'billing-trials-daily': {
        'task': 'billing.tasks.expire_trials_and_notify',
        'schedule': crontab(hour='13', minute='0'),
    },
    # Anonymous public comparisons: purge expired results + stray files.
    'purge-public-comparisons-hourly': {
        'task': 'public_tools.tasks.purge_expired_public_comparisons',
        'schedule': crontab(minute='20'),
    },
}

# ---------------------------------------------------------------------------
# Query Profiling (django-silk) — enabled via ENABLE_SILK env var
# Production-only: DB recording for slow-query and N+1 monitoring.
# The /silk/ UI is intentionally not exposed (see urls.py).
# ---------------------------------------------------------------------------
if ENABLE_SILK:
    SILKY_ANALYZE_QUERIES = True

    SILKY_AUTHENTICATION = True
    SILKY_AUTHORISATION = True

    def silk_permissions(user):
        return user.is_staff

    SILKY_PERMISSIONS = silk_permissions

    SILKY_MAX_RECORDED_REQUESTS = 10_000
    SILKY_MAX_RECORDED_REQUESTS_CHECK_PERCENT = 10

    SILKY_IGNORE_PATHS = [
        '/admin/',
        '/static/',
        '/media/',
        '/silk/',
    ]

    SILKY_MAX_REQUEST_BODY_SIZE = 0
    SILKY_MAX_RESPONSE_BODY_SIZE = 0

    def _silk_intercept(request):
        return request.path.startswith('/api/')

    SILKY_INTERCEPT_FUNC = _silk_intercept

SLOW_QUERY_THRESHOLD_MS = int(os.getenv('SLOW_QUERY_THRESHOLD_MS', '500'))
N_PLUS_ONE_THRESHOLD = int(os.getenv('N_PLUS_ONE_THRESHOLD', '10'))

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000').rstrip('/')

# ---------------------------------------------------------------------------
# Versiona domain settings (kit — nothing hardcoded, docs/plan/07 §2)
# ---------------------------------------------------------------------------
TRASH_RETENTION_DAYS = int(os.getenv('TRASH_RETENTION_DAYS', '30'))
MAX_PDF_SIZE_MB = int(os.getenv('MAX_PDF_SIZE_MB', '25'))
UPLOAD_SIGNED_URL_TTL_SECONDS = int(os.getenv('UPLOAD_SIGNED_URL_TTL_SECONDS', '900'))
D5_DEFAULT_MODE = os.getenv('D5_DEFAULT_MODE', 'auto')
D5_OCR_CONFIDENCE_MIN = float(os.getenv('D5_OCR_CONFIDENCE_MIN', '0.75'))
BILLING_TRIAL_DAYS = int(os.getenv('BILLING_TRIAL_DAYS', '14'))
PUBLIC_COMPARE_MAX_PDF_SIZE_MB = int(os.getenv('PUBLIC_COMPARE_MAX_PDF_SIZE_MB', '10'))
PUBLIC_COMPARE_MAX_PAGES = int(os.getenv('PUBLIC_COMPARE_MAX_PAGES', '100'))
PUBLIC_COMPARE_TTL_HOURS = int(os.getenv('PUBLIC_COMPARE_TTL_HOURS', '24'))
