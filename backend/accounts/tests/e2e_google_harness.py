"""Private E2E launcher: replace only the official Google tokeninfo transport.

Run from backend: python -m accounts.tests.e2e_google_harness runserver HOST:PORT --noreload
The operator must explicitly coordinate the disposable database and object root.
"""
import base64
import json
import os
import sys
from pathlib import Path


def _guard(settings):
    database = settings.DATABASES['default']
    expected_db = os.environ.get('E2E_GOOGLE_HARNESS_DB_NAME', '')
    expected_root = os.environ.get('E2E_GOOGLE_HARNESS_STORAGE_ROOT', '')
    root = Path(settings.OBJECT_STORAGE_ROOT).resolve()
    if (
        os.environ.get('E2E_GOOGLE_HARNESS') != '1'
        or not expected_db.startswith('versiona_e2e_')
        or database.get('ENGINE') != 'django.db.backends.mysql'
        or database.get('NAME') != expected_db
        or database.get('HOST') not in ('localhost', '127.0.0.1')
        or str(database.get('PORT')) in ('', '3306')
        or not expected_root or root != Path(expected_root).resolve()
        or not root.is_relative_to(Path('/tmp'))
        or settings.OBJECT_STORAGE_SENDFILE_ROOT
        or settings.IS_PRODUCTION
        or not settings.GOOGLE_OAUTH_CLIENT_ID
    ):
        raise SystemExit('Google E2E harness requires the coordinated private database and storage.')


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'versiona_project.settings')
    import django
    django.setup()
    from django.conf import settings
    _guard(settings)
    from accounts.services import google_identity_service as google
    from django.core.management import execute_from_command_line

    original_get = google.requests.get

    class Response:
        def __init__(self, payload=None):
            self.status_code = 200 if payload is not None else 400
            self.payload = payload

        def json(self):
            return self.payload

    def google_transport(url, *args, **kwargs):
        if url != google.TOKENINFO_URL:
            return original_get(url, *args, **kwargs)
        credential = kwargs.get('params', {}).get('id_token', '')
        try:
            prefix, encoded = credential.split('.', 1)
            if prefix != 'VERSIONA_E2E':
                return Response()
            payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            if (not isinstance(payload, dict)
                    or not isinstance(payload.get('email'), str)
                    or not payload['email'].endswith('@versiona.test')
                    or not isinstance(payload.get('sub'), str)
                    or not payload['sub'].startswith('e2e-google:')):
                return Response()
            # The application itself checks audience, expiry, issuer and email proof.
            return Response(payload)
        except (ValueError, TypeError, UnicodeError):
            return Response()

    google.requests.get = google_transport
    if len(sys.argv) < 2 or sys.argv[1] != 'runserver' or '--noreload' not in sys.argv:
        raise SystemExit('Harness only supports runserver with --noreload.')
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
