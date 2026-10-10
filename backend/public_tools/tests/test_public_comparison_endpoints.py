"""POST/GET /api/public/comparisons/ — AllowAny, validated, throttled."""

import copy
import importlib.util
import os
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from public_tools.models import PublicComparison
from public_tools.views import (
    PublicCompareDailyThrottle,
    PublicCompareStatusThrottle,
    PublicCompareThrottle,
)

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'
URL = '/api/public/comparisons/'
PUBLIC_CLIENT_IP = '198.51.100.24'
OTHER_PUBLIC_CLIENT_IP = '198.51.100.25'
FORWARDED_PREFIXES = (
    pytest.param('192.0.2.{}', id='ipv4-prefix'),
    pytest.param('2001:db8:ffff::{}', id='ipv6-prefix'),
)


@pytest.fixture(autouse=True)
def _clean_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def upload(name: str, content: bytes | None = None) -> SimpleUploadedFile:
    data = content if content is not None else (TESTDATA / name).read_bytes()
    return SimpleUploadedFile(name, data, content_type='application/pdf')


def post_pair(api_client, file_a, file_b):
    return api_client.post(URL, {'file_a': file_a, 'file_b': file_b},
                           format='multipart')


@pytest.fixture
def production_proxy_framework(settings, monkeypatch, tmp_path):
    """Execute real production settings in private modules without service I/O."""
    settings_dir = Path(__file__).resolve().parents[2] / 'versiona_project'
    package_name = '_versiona_private_public_settings'
    package = types.ModuleType(package_name)
    package.__path__ = [str(settings_dir)]
    monkeypatch.setitem(sys.modules, package_name, package)
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    private_environment = {
        'DJANGO_SECRET_KEY': 'private-settings-test-only',
        'DJANGO_ALLOWED_HOSTS': 'testserver',
        'DJANGO_ENV': 'test',
        'DJANGO_DB_ENGINE': 'django.db.backends.sqlite3',
        'DJANGO_DB_NAME': ':memory:',
    }
    # Only filesystem boundaries are replaced. NUM_PROXIES and rates come from
    # the real base/production modules, never from constants in these tests.
    with patch.dict(os.environ, private_environment, clear=True), \
            patch('dotenv.load_dotenv', return_value=False), patch('pathlib.Path.mkdir'):
        for name in ('db', 'settings', 'settings_prod'):
            spec = importlib.util.spec_from_file_location(
                f'{package_name}.{name}', settings_dir / f'{name}.py',
            )
            module = importlib.util.module_from_spec(spec)
            module.__file__ = str(tmp_path / 'backend' / 'versiona_project' / f'{name}.py')
            monkeypatch.setitem(sys.modules, spec.name, module)
            spec.loader.exec_module(module)

    settings.REST_FRAMEWORK = copy.deepcopy(module.REST_FRAMEWORK)
    # These classes cache their rate map at import time. Refresh it from the
    # configuration just loaded; preserve the actual production limits.
    for throttle in (PublicCompareThrottle, PublicCompareDailyThrottle, PublicCompareStatusThrottle):
        monkeypatch.setattr(throttle, 'THROTTLE_RATES', settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'])
        monkeypatch.setattr(throttle, 'timer', staticmethod(lambda: 1_700_000_000))
    cache.clear()
    yield
    cache.clear()


def _post_forwarded_comparison(client, prefix, attempt, client_ip=PUBLIC_CLIENT_IP):
    """Use missing files to exercise admission without running the PDF pipeline."""
    return client.post(
        URL, {}, format='multipart', REMOTE_ADDR='',
        HTTP_X_FORWARDED_FOR=f'{prefix.format(attempt)}, {client_ip}',
    )


def _consume_forwarded_public_quota(client, prefix, count, client_ip=PUBLIC_CLIENT_IP):
    """Consume the preceding budget with distinct untrusted header prefixes."""
    return [
        _post_forwarded_comparison(client, prefix, attempt, client_ip).status_code
        for attempt in range(1, count + 1)
    ]


@pytest.mark.parametrize('prefix', FORWARDED_PREFIXES)
def test_production_public_hourly_quota_rejects_rotating_forwarded_prefix(
    api_client, production_proxy_framework, prefix,
):
    """Fails if a forged prefix restarts the public comparator's hourly quota."""
    # Arrange
    preceding_statuses = _consume_forwarded_public_quota(api_client, prefix, 10)

    # Act
    response = _post_forwarded_comparison(api_client, prefix, 11)

    # Assert
    assert preceding_statuses == [400] * 10
    assert response.status_code == 429
    assert response['Retry-After'] != ''


@pytest.mark.parametrize('prefix', FORWARDED_PREFIXES)
def test_production_public_daily_quota_rejects_rotating_forwarded_prefix(
    api_client, production_proxy_framework, monkeypatch, prefix,
):
    """Fails if forged prefixes evade the daily budget across hourly windows."""
    # Arrange
    first_hour = _consume_forwarded_public_quota(api_client, prefix, 10)
    monkeypatch.setattr(PublicCompareThrottle, 'timer', staticmethod(lambda: 1_700_003_601))
    monkeypatch.setattr(PublicCompareDailyThrottle, 'timer', staticmethod(lambda: 1_700_003_601))
    second_hour = _consume_forwarded_public_quota(api_client, prefix, 10)
    monkeypatch.setattr(PublicCompareThrottle, 'timer', staticmethod(lambda: 1_700_007_202))
    monkeypatch.setattr(PublicCompareDailyThrottle, 'timer', staticmethod(lambda: 1_700_007_202))
    third_hour = _consume_forwarded_public_quota(api_client, prefix, 10)
    monkeypatch.setattr(PublicCompareThrottle, 'timer', staticmethod(lambda: 1_700_010_803))
    monkeypatch.setattr(PublicCompareDailyThrottle, 'timer', staticmethod(lambda: 1_700_010_803))

    # Act
    response = _post_forwarded_comparison(api_client, prefix, 31)

    # Assert
    assert first_hour == [400] * 10
    assert second_hour == [400] * 10
    assert third_hour == [400] * 10
    assert response.status_code == 429


@pytest.mark.parametrize('prefix', FORWARDED_PREFIXES)
def test_production_public_quota_preserves_an_independent_client_budget(
    api_client, production_proxy_framework, prefix,
):
    """Fails if the proxy socket address merges distinct public client budgets."""
    # Arrange
    exhausted_statuses = _consume_forwarded_public_quota(api_client, prefix, 10)

    # Act
    independent_statuses = _consume_forwarded_public_quota(
        api_client, prefix, 10, OTHER_PUBLIC_CLIENT_IP,
    )
    response = _post_forwarded_comparison(api_client, prefix, 11, OTHER_PUBLIC_CLIENT_IP)

    # Assert
    assert exhausted_statuses == [400] * 10
    assert independent_statuses == [400] * 10
    assert response.status_code == 429


@pytest.mark.django_db
@pytest.mark.escenario('PC-F01')
def test_post_happy_path_returns_done_result_in_eager_mode(api_client):
    response = post_pair(
        api_client, upload('contrato_v1.pdf'), upload('contrato_v2.pdf')
    )

    assert response.status_code == 202
    detail = api_client.get(response.data['status_url'])
    assert detail.data['status'] == 'done'
    assert detail.data['result']['summary_text'] == (
        '2 modificadas, 1 eliminada, 1 agregada'
    )


@pytest.mark.django_db
@pytest.mark.escenario('PC-F02')
def test_post_creates_no_org_project_document_rows(api_client):
    from documents.models import Document, DocumentVersion
    from orgs.models import Organization
    from projects.models import Project

    post_pair(api_client, upload('contrato_v1.pdf'), upload('contrato_v2.pdf'))

    assert Organization.objects.count() == 0
    assert Project.objects.count() == 0
    assert Document.all_objects.count() == 0
    assert DocumentVersion.all_objects.count() == 0


@pytest.mark.django_db
@pytest.mark.escenario('PC-E01')
def test_post_rejects_oversize_file_with_413(api_client):
    heavy = upload('pesado.pdf', b'%PDF-' + b'0' * (11 * 1024 * 1024))

    response = post_pair(api_client, heavy, upload('contrato_v2.pdf'))

    assert response.status_code == 413
    assert response.data['error_code'] == 'too_big'


@pytest.mark.django_db
@pytest.mark.escenario('PC-E02')
def test_post_rejects_non_pdf_with_415(api_client):
    fake = upload('archivo.pdf', b'GIF89a not a pdf at all')

    response = post_pair(api_client, fake, upload('contrato_v2.pdf'))

    assert response.status_code == 415
    assert response.data['error_code'] == 'not_pdf'


@pytest.mark.django_db
@pytest.mark.escenario('PC-E03')
def test_post_rejects_encrypted_pdf_with_400(api_client):
    response = post_pair(
        api_client, upload('protegido.pdf'), upload('contrato_v2.pdf')
    )

    assert response.status_code == 400
    assert response.data['error_code'] == 'encrypted_pdf'


@pytest.mark.django_db
@pytest.mark.escenario('PC-E04')
def test_post_rejects_scanned_pdf_with_422_ocr_required(api_client):
    response = post_pair(
        api_client, upload('escaneado_v1.pdf'), upload('contrato_v2.pdf')
    )

    assert response.status_code == 422
    assert response.data['error_code'] == 'ocr_required'


@pytest.mark.django_db
@pytest.mark.escenario('PC-E05')
def test_post_rejects_page_count_over_cap_with_422(api_client, settings):
    settings.PUBLIC_COMPARE_MAX_PAGES = 1

    response = post_pair(
        api_client, upload('contrato_v1.pdf'), upload('contrato_v2.pdf')
    )

    assert response.status_code == 422
    assert response.data['error_code'] == 'too_many_pages'


@pytest.mark.django_db
@pytest.mark.escenario('PC-E06')
def test_post_throttled_returns_429(api_client, monkeypatch):
    monkeypatch.setattr(PublicCompareThrottle, 'rate', '1/hour', raising=False)

    post_pair(api_client, upload('contrato_v1.pdf'), upload('contrato_v2.pdf'))
    second = post_pair(
        api_client, upload('contrato_v1.pdf'), upload('contrato_v2.pdf')
    )

    assert second.status_code == 429


@pytest.mark.django_db
@pytest.mark.escenario('PC-E07')
def test_get_unknown_id_returns_404(api_client):
    response = api_client.get(
        f'{URL}0198c9a0-0000-7000-8000-000000000000/'
    )

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.escenario('PC-E08')
def test_get_expired_row_returns_410_with_expired_code(api_client):
    comparison = PublicComparison.objects.create(
        status=PublicComparison.Status.DONE,
        result={'counts': {}},
        expires_at=timezone.now() - timedelta(hours=1),
    )

    response = api_client.get(f'{URL}{comparison.public_id}/')

    assert response.status_code == 410
    assert response.data['error_code'] == 'expired'
