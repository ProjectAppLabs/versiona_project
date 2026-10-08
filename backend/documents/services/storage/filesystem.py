"""Filesystem object storage.

Same contract as the S3 backend, so nothing in the domain layer knows which one
is running. Objects live under ``settings.OBJECT_STORAGE_ROOT`` — deliberately
OUTSIDE ``MEDIA_ROOT``, which ``urls.py`` serves unsigned under DEBUG and which
nginx publishes as ``/media/``. That separation is what makes "signed URL only"
a real property rather than a convention; a system check enforces it.

The signed URL replaces the S3 presigned URL and carries the same guarantees: it
names exactly one key, one HTTP method and one content type, and it expires.
The payload is HMAC'd with SECRET_KEY, so ``exp`` cannot be pushed forward by
whoever holds the token.
"""

import contextlib
import mimetypes
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.urls import reverse

from .base import ObjectTooLarge, StorageUnavailable

# Scopes these signatures: a token minted here is useless against any other
# signing.dumps() consumer in the project, even though they share SECRET_KEY.
SIGNING_SALT = 'documents.storage.object.v1'
TOKEN_VERSION = 1

UPLOAD_CONTENT_TYPE = 'application/pdf'

# Positive match: structurally cannot express '..', an absolute path, a
# backslash or a NUL byte. Belt to safe_join()'s braces.
_KEY_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]*(/[A-Za-z0-9][A-Za-z0-9._\-]*)*$')
_MAX_KEY_LEN = 1024

_STREAM_CHUNK = 64 * 1024


class InvalidObjectToken(Exception):
    """Signed token that is forged, malformed, expired or scoped to another method."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# ---------------------------------------------------------------------------
# Key → path
# ---------------------------------------------------------------------------
def _root() -> str:
    return str(settings.OBJECT_STORAGE_ROOT)


def resolve_path(key: str) -> Path:
    """Map a storage key to an absolute path, refusing anything outside the root.

    Two independent layers: a positive-match regex, then Django's own
    ``safe_join`` (via FileSystemStorage.path) which normalises and asserts
    containment. Raises SuspiciousFileOperation — deliberately NOT
    StorageUnavailable, which serializers.py swallows to degrade thumbnails: a
    malformed key is a bug or an attack, never a soft miss.
    """
    if not key or not isinstance(key, str) or len(key) > _MAX_KEY_LEN:
        raise SuspiciousFileOperation(f'Invalid object key: {key!r}')
    if not _KEY_RE.match(key) or '..' in key.split('/'):
        raise SuspiciousFileOperation(f'Invalid object key: {key!r}')
    return Path(FileSystemStorage(location=_root()).path(key))


def _ensure_dir(directory: Path) -> None:
    root = Path(_root()).resolve()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageUnavailable(f'Object root is not writable: {exc}') from exc
    mode = getattr(settings, 'OBJECT_STORAGE_DIR_MODE', 0o750)
    current = directory
    while current != root and root in current.parents:
        with contextlib.suppress(OSError):
            os.chmod(current, mode)
        current = current.parent


# ---------------------------------------------------------------------------
# Signed URLs
# ---------------------------------------------------------------------------
def _expires_at(ttl: int | None, setting_name: str, fallback: int) -> int:
    seconds = ttl or int(getattr(settings, setting_name, fallback))
    return int(time.time()) + int(seconds)


def _signed_url(payload: dict) -> str:
    payload['v'] = TOKEN_VERSION
    token = signing.dumps(payload, salt=SIGNING_SALT, compress=True)
    path = reverse('object-access', kwargs={'token': token})
    # Root-relative by default: the browser PUTs with a bare axios call, which
    # resolves against window.location.origin — the very origin nginx serves.
    # That keeps the URL correct from any hostname the app answers on (domain,
    # tailscale IP, staging alias) and avoids a CORS preflight. The override
    # exists for the rare caller that needs an absolute URL.
    origin = (getattr(settings, 'OBJECT_STORAGE_PUBLIC_ORIGIN', '') or '').rstrip('/')
    return f'{origin}{path}' if origin else path


def verify_token(token: str, method: str) -> dict:
    """Validate a signed token for `method`, or raise InvalidObjectToken."""
    try:
        payload = signing.loads(token, salt=SIGNING_SALT)
    except signing.BadSignature as exc:
        raise InvalidObjectToken('signature_invalid') from exc
    if payload.get('v') != TOKEN_VERSION or payload.get('m') != method:
        raise InvalidObjectToken('signature_invalid')
    if int(payload.get('exp', 0)) < time.time():
        raise InvalidObjectToken('signature_expired')
    return payload


def presign_upload(key: str, ttl: int | None = None) -> str:
    return _signed_url({
        'k': key,
        'm': 'PUT',
        'ct': UPLOAD_CONTENT_TYPE,
        'exp': _expires_at(ttl, 'UPLOAD_SIGNED_URL_TTL_SECONDS', 900),
    })


def presign_download(key: str, filename: str, ttl: int | None = None) -> str:
    return _signed_url({
        'k': key,
        'm': 'GET',
        'ct': 'application/pdf',
        'd': 'attachment',
        'fn': filename,
        'exp': _expires_at(ttl, 'MEDIA_SIGNED_URL_TTL_SECONDS', 300),
    })


def presign_view(key: str, content_type: str, ttl: int | None = None) -> str:
    """Inline variant for the in-app viewer/thumbnails (react-pdf needs GET)."""
    return _signed_url({
        'k': key,
        'm': 'GET',
        'ct': content_type,
        'd': 'inline',
        'exp': _expires_at(ttl, 'MEDIA_SIGNED_URL_TTL_SECONDS', 300),
    })


# ---------------------------------------------------------------------------
# Object operations
# ---------------------------------------------------------------------------
def head(key: str) -> dict | None:
    """Object metadata, or None when absent.

    Keeps S3's PascalCase keys so call sites never branch on the backend. ETag
    is a size+mtime validator in nginx's style, NOT a content digest — hashing
    25 MB on every probe would be absurd and nothing consumes it.
    """
    path = resolve_path(key)
    try:
        st = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not path.is_file():
        return None
    return {
        'ContentLength': st.st_size,
        'ContentType': mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
        'LastModified': datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        'ETag': f'"{st.st_size:x}-{st.st_mtime_ns:x}"',
    }


def get_bytes(key: str) -> bytes:
    path = resolve_path(key)
    try:
        return path.read_bytes()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise StorageUnavailable(f'Object not found: {key}') from exc


def put_stream(key: str, chunks: Iterable[bytes], max_bytes: int | None = None) -> int:
    """Write an object from an iterable of chunks, atomically. Returns the size.

    Temp file in the SAME directory + os.replace: atomic only within one
    filesystem, which co-locating guarantees. A crash mid-write can therefore
    never leave a truncated object behind a valid key.
    """
    path = resolve_path(key)
    _ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    total = 0
    try:
        with os.fdopen(fd, 'wb') as handle:
            for chunk in chunks:
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise ObjectTooLarge(f'Object exceeds {max_bytes} bytes')
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, getattr(settings, 'OBJECT_STORAGE_FILE_MODE', 0o640))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return total


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    """content_type is accepted for parity with S3 and ignored: it is supplied
    by the caller when the URL is signed, so there is nothing to persist."""
    put_stream(key, [data])


def copy(source_key: str, dest_key: str) -> None:
    """Hardlink when possible — O(1), no bytes moved, no extra disk.

    Safe precisely because every write goes temp+rename: os.replace swaps a
    directory entry and never mutates an inode in place, so the two names can
    never diverge. That is what lets complete_upload copy the staging key to the
    immutable version key and then delete the staging key.
    """
    src = resolve_path(source_key)
    dst = resolve_path(dest_key)
    _ensure_dir(dst.parent)
    try:
        os.link(src, dst)
    except FileExistsError:
        pass  # immutable keys: already present == already done
    except OSError:  # EXDEV / EMLINK / filesystem without hardlinks
        with src.open('rb') as handle:
            put_stream(dest_key, iter(lambda: handle.read(_STREAM_CHUNK), b''))


def delete(key: str) -> None:
    """Idempotent, like S3's delete_object — complete_upload and the public
    comparison purge both call it on keys that may already be gone.

    Other filesystem failures must reach the caller so a failed deletion never
    gets mistaken for a missing object.
    """
    path = resolve_path(key)
    path.unlink(missing_ok=True)
