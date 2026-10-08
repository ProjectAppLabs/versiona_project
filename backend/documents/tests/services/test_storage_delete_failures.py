"""Real filesystem failures must remain distinguishable from absent objects."""

import pytest

from documents.services import storage_service
from documents.services.storage import filesystem

KEY = 'test/delete-failures/private.pdf'
PAYLOAD = b'%PDF-1.7 private fixture'


def test_delete_reports_permission_failure():
    """Propagate permission errors without deleting the stored object."""
    storage_service.put_bytes(KEY, PAYLOAD, 'application/pdf')
    path = filesystem.resolve_path(KEY)
    path.parent.chmod(0o500)

    try:
        with pytest.raises(PermissionError):
            storage_service.delete(KEY)
    finally:
        path.parent.chmod(0o750)

    assert storage_service.get_bytes(KEY) == PAYLOAD
    storage_service.delete(KEY)
    assert storage_service.head(KEY) is None


def test_delete_reports_directory_failure():
    """Reject directory deletion while preserving its contents."""
    path = filesystem.resolve_path(KEY)
    path.mkdir(parents=True)
    child = path / 'retained.pdf'
    child.write_bytes(PAYLOAD)

    with pytest.raises(IsADirectoryError):
        storage_service.delete(KEY)

    assert child.read_bytes() == PAYLOAD
