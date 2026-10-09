"""
Version lifecycle services (flows C1/C2/C3 — docs/plan/03 §3, docs/audit/03).

Upload is two-step (DP-06): `create_upload_intent` hands out a presigned PUT
to a staging key; `complete_upload` is the authority — it verifies the object
(magic bytes + full parse + size), computes sha256 server-side (I9), rejects
duplicates (C2-E01/F6), serializes the version number (I1) and enqueues the
analysis job.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils.text import slugify

from audit import services as audit
from documents.models import Document, DocumentVersion
from documents.services import storage_service
from engine.services.analysis import EncryptedPdfError, InvalidPdfError, open_pdf
from engine.tasks import enqueue_analysis
from projects.models import Project, ProjectConfigVersion

logger = logging.getLogger(__name__)


# MySQL ER_LOCK_WAIT_TIMEOUT.
ER_LOCK_WAIT_TIMEOUT = 1205


class DomainError(Exception):
    """Business rejection: carries an HTTP status and a user-facing message."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def ensure_writable(project: Project):
    if project.is_read_only:
        raise DomainError('El proyecto está archivado o en la papelera: es de solo lectura.', 409)


def max_upload_bytes() -> int:
    return int(getattr(settings, 'MAX_PDF_SIZE_MB', 25)) * 1024 * 1024


def create_document(project: Project, title: str, user, request=None) -> Document:
    ensure_writable(project)
    title = (title or '').strip()
    if not title:
        raise DomainError('El título del documento es obligatorio.', 400)
    base = slugify(title)[:200] or 'documento'
    slug = base
    suffix = 1
    while Document.objects.filter(project=project, slug=slug).exists():
        suffix += 1
        slug = f'{base}-{suffix}'
    document = Document.objects.create(project=project, title=title, slug=slug)
    audit.record(org=project.organization, project=project, actor=user,
                 event_type='document.created', obj=document,
                 payload={'title': title}, request=request)
    return document


@dataclass
class UploadIntent:
    upload_id: str
    key: str
    url: str
    max_bytes: int


def create_upload_intent(document: Document, user) -> UploadIntent:
    ensure_writable(document.project)
    upload_id = storage_service.new_upload_id()
    key = storage_service.staging_key(document.project.organization, upload_id)
    return UploadIntent(
        upload_id=upload_id,
        key=key,
        url=storage_service.presign_upload(key),
        max_bytes=max_upload_bytes(),
    )


def complete_upload(document: Document, upload_id: str, message: str, user, request=None):
    """Returns (version, job). C1-F01 / C2-F01 backend slice."""
    ensure_writable(document.project)
    staging = storage_service.staging_key(document.project.organization, upload_id)
    meta = storage_service.head(staging)
    if meta is None:
        raise DomainError('No se encontró el archivo subido: repite la subida.', 400)
    size = int(meta.get('ContentLength', 0))
    if size <= 0:
        raise DomainError('El archivo subido está vacío.', 400)
    if size > max_upload_bytes():
        raise DomainError(
            f'El archivo supera el límite de {max_upload_bytes() // (1024 * 1024)} MB del plan.',
            413,
        )

    data = storage_service.get_bytes(staging)
    # Metadata and staging may change between reads. This captured object is
    # the only authority for validation, its persisted metadata and promotion.
    size = len(data)
    if size <= 0:
        raise DomainError('El archivo subido está vacío.', 400)
    if size > max_upload_bytes():
        raise DomainError(
            f'El archivo supera el límite de {max_upload_bytes() // (1024 * 1024)} MB del plan.',
            413,
        )
    if not data.startswith(b'%PDF-'):
        raise DomainError('El archivo no es un PDF válido.', 400)
    try:
        pdf = open_pdf(data)
        pdf.close()
    except EncryptedPdfError:
        raise DomainError(
            'El PDF está protegido con contraseña: quita la protección y vuelve a subirlo.', 400
        )
    except InvalidPdfError:
        raise DomainError('El archivo está corrupto o no es un PDF legible.', 400)

    sha256 = storage_service.sha256_of(data)

    try:
        version = _create_locked_version(document, data, sha256, size, message, user, request)
    except OperationalError as exc:
        # _create_locked_version holds its row lock across storage_service.put_bytes(),
        # so a second
        # upload to the same document waits on network I/O. PostgreSQL waited
        # forever; InnoDB gives up after innodb_lock_wait_timeout (50s) with
        # error 1205, which would otherwise surface as a 500.
        if exc.args and exc.args[0] == ER_LOCK_WAIT_TIMEOUT:
            raise DomainError(
                'Otra subida sobre este documento está en curso; intenta de nuevo.', 409
            ) from exc
        raise

    try:
        storage_service.delete(staging)
    except OSError as exc:
        # Promotion is committed; cleanup must not prevent analysis or turn a
        # completed upload into a failure response. Leave the temporary object
        # intact and report only safe diagnostics.
        logger.warning(
            'Staging upload cleanup failed after promotion: phase=upload_cleanup error_class=%s',
            type(exc).__name__,
            extra={'phase': 'upload_cleanup', 'error_class': type(exc).__name__},
        )
    job = enqueue_analysis(version)
    version.refresh_from_db()
    return version, job


def _create_locked_version(document, data, sha256, size, message, user, request):
    """I1: allocating the version number and writing the object happen under one
    document-row lock, so two concurrent uploads cannot claim the same number."""
    with transaction.atomic():
        locked = Document.objects.select_for_update().get(pk=document.pk)
        # F6 compares with the CURRENT version: the alive one no alive version
        # supersedes (documents.queries), not the allocation counter.
        current = (
            DocumentVersion.objects.filter(document=locked)
            .order_by('-number')
            .only('number', 'sha256')
            .first()
        )
        if current and current.sha256 == sha256:
            raise DomainError(
                f'El archivo es idéntico a la versión v{current.number}.', 409
            )
        number = locked.latest_number + 1
        final_key = storage_service.version_key(locked, number)
        # Promote precisely the bytes validated above, even if the signed PUT
        # token replaces the staging object before this row lock is acquired.
        storage_service.put_bytes(final_key, data, 'application/pdf')
        version = DocumentVersion.objects.create(
            document=locked,
            number=number,
            message=(message or '').strip(),
            sha256=sha256,
            file_key=final_key,
            size_bytes=size,
            author=user,
            config_version=ProjectConfigVersion.current_for(locked.project),
        )
        locked.latest_number = number
        locked.save(update_fields=['latest_number', 'updated_at'])
        # D1: reviewing an outdated version is pointless — supersede open
        # requests on older versions of this document.
        from reviews.services.review_service import supersede_open_requests

        supersede_open_requests(version)
        audit.record(org=locked.project.organization, project=locked.project, actor=user,
                     event_type='version.uploaded', obj=version,
                     payload={'number': number, 'sha256': sha256, 'size': size},
                     request=request)

    return version


def edit_message(version: DocumentVersion, message: str, user, request=None) -> DocumentVersion:
    """I2b: message editable only while draft (C2-A01 / C2-E02)."""
    ensure_writable(version.document.project)
    if not version.is_draft:
        raise DomainError(
            'El mensaje quedó congelado: la versión tiene sellos, solicitud o aprobación.', 409
        )
    before = version.message
    version.message = (message or '').strip()
    version.save(update_fields=['message', 'updated_at'])
    audit.record(org=version.document.project.organization,
                 project=version.document.project, actor=user,
                 event_type='version.message_edited', obj=version,
                 payload={'before': before, 'after': version.message}, request=request)
    return version


def download_url(version: DocumentVersion, user, request=None) -> str:
    filename = f'{version.document.slug}-v{version.number}.pdf'
    url = storage_service.presign_download(version.file_key, filename)
    audit.record(org=version.document.project.organization,
                 project=version.document.project, actor=user,
                 event_type='version.downloaded', obj=version,
                 payload={'number': version.number}, request=request)
    return url
