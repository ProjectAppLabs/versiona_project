"""Upload-intent quota contracts for authenticated document editors."""

from pathlib import Path

import pytest
from django.core.cache import cache

from documents.services import version_service
from documents.views import UploadThrottle

TESTDATA = Path(__file__).resolve().parents[4] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def isolated_upload_quota(monkeypatch):
    """Keep each quota assertion independent from DRF's shared cache."""
    cache.clear()
    monkeypatch.setattr(UploadThrottle, 'get_rate', lambda self: '2/hour')
    yield
    cache.clear()


@pytest.fixture
def upload_documents(versiona_context):
    """Create two editable documents for one authenticated quota subject."""
    editor = versiona_context.users['editor']
    return [
        version_service.create_document(versiona_context.project, title, editor)
        for title in ('Contrato uno', 'Contrato dos')
    ]


def _intent(client, document):
    """Request one upload capability through the public API."""
    return client.post(f'/api/documents/{document.public_id}/versions/upload_intent/')


@pytest.mark.django_db
def test_upload_intent_rejects_third_request_from_same_editor(client_as, upload_documents):
    """Catches: an upload quota that is skipped or grants a third capability."""
    editor = client_as('editor')

    first = _intent(editor, upload_documents[0])
    second = _intent(editor, upload_documents[1])
    rejected = _intent(editor, upload_documents[0])

    assert first.status_code == 200
    assert second.status_code == 200
    assert rejected.status_code == 429
    assert int(rejected['Retry-After']) > 0
    assert 'upload_id' not in rejected.data
    assert 'url' not in rejected.data


@pytest.mark.django_db
def test_upload_intent_quota_isolated_by_authenticated_user(client_as, upload_documents):
    """Catches: a shared-IP throttle that exhausts uploads for another member."""
    editor = client_as('editor')

    assert _intent(editor, upload_documents[0]).status_code == 200
    assert _intent(editor, upload_documents[1]).status_code == 200
    response = _intent(client_as('admin'), upload_documents[0])

    assert response.status_code == 200
    assert 'upload_id' in response.data


@pytest.mark.django_db
def test_upload_intent_accepts_request_after_hour_window(client_as, upload_documents, monkeypatch):
    """Catches: expired upload quota entries that block an editor permanently."""
    now = [1_700_000_000.0]
    monkeypatch.setattr(UploadThrottle, 'timer', lambda _throttle: now[0])
    editor = client_as('editor')

    assert _intent(editor, upload_documents[0]).status_code == 200
    assert _intent(editor, upload_documents[1]).status_code == 200
    now[0] += 3601
    response = _intent(editor, upload_documents[0])

    assert response.status_code == 200


@pytest.mark.django_db
def test_issued_upload_capability_completes_after_quota_exhaustion(client_as, upload_documents):
    """Catches: quota exhaustion invalidating a capability already issued to the editor."""
    editor = client_as('editor')
    first = _intent(editor, upload_documents[0])
    assert first.status_code == 200
    assert _intent(editor, upload_documents[1]).status_code == 200
    assert _intent(editor, upload_documents[0]).status_code == 429

    uploaded = editor.put(
        first.data['url'], data=(TESTDATA / 'contrato_v1.pdf').read_bytes(),
        content_type='application/pdf',
    )
    completed = editor.post(
        f'/api/documents/{upload_documents[0].public_id}/versions/complete/',
        {'upload_id': first.data['upload_id'], 'message': 'cuota emitida'}, format='json',
    )

    assert uploaded.status_code == 200
    assert completed.status_code == 202
