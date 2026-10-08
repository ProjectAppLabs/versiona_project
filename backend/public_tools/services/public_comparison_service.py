"""Anonymous two-PDF comparison: validation, ephemeral storage and the diff.

Reuses the engine's pure pipeline (`analyze_bytes` with OCR disallowed +
`compare_snapshots`) exactly like the authenticated E1 flow — no
DocumentVersion involved, no seal/D5 code path touched.
"""

from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from documents.services import storage_service
from engine.services.analysis import (
    EncryptedPdfError,
    InvalidPdfError,
    analyze_bytes,
    open_pdf,
)
from engine.services.comparison import compare_snapshots

from ..models import PublicComparison


class PublicCompareError(Exception):
    """User-facing validation error (Spanish message + machine error_code)."""

    def __init__(self, message: str, status_code: int, error_code: str):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def max_upload_bytes() -> int:
    return settings.PUBLIC_COMPARE_MAX_PDF_SIZE_MB * 1024 * 1024


def storage_key_for(public_id, slot: str) -> str:
    prefix = storage_service._env_prefix()
    return f'{prefix}/public-compare/{public_id}/{slot}.pdf'


def validate_public_pdf(uploaded_file) -> bytes:
    """Full validation chain; returns the file bytes when acceptable."""
    if uploaded_file is None:
        raise PublicCompareError(
            'Necesitas dos PDF para comparar.', 400, 'missing_files'
        )

    name = Path(uploaded_file.name or '').name
    content_type = (uploaded_file.content_type or '').lower()
    if not name.lower().endswith('.pdf') and content_type != 'application/pdf':
        raise PublicCompareError('Ese archivo no es un PDF.', 415, 'not_pdf')

    if uploaded_file.size > max_upload_bytes():
        raise PublicCompareError(
            f'El archivo supera el límite de '
            f'{settings.PUBLIC_COMPARE_MAX_PDF_SIZE_MB} MB de la comparación '
            'gratuita.',
            413,
            'too_big',
        )

    data = uploaded_file.read()
    if not data.startswith(b'%PDF-'):
        raise PublicCompareError('Ese archivo no es un PDF.', 415, 'not_pdf')

    try:
        doc = open_pdf(data)
    except EncryptedPdfError as exc:
        raise PublicCompareError(
            'El PDF está protegido con contraseña: quita la protección e '
            'inténtalo de nuevo.',
            400,
            'encrypted_pdf',
        ) from exc
    except InvalidPdfError as exc:
        raise PublicCompareError(
            'El archivo está corrupto o no es un PDF legible.',
            400,
            'invalid_pdf',
        ) from exc

    try:
        if doc.page_count > settings.PUBLIC_COMPARE_MAX_PAGES:
            raise PublicCompareError(
                f'El PDF supera las {settings.PUBLIC_COMPARE_MAX_PAGES} '
                'páginas de la comparación gratuita.',
                422,
                'too_many_pages',
            )
        from engine.services.analysis import detect_scenario

        if detect_scenario(doc) == 'scanned_ocr':
            raise PublicCompareError(
                'Los PDF escaneados requieren OCR — créate una cuenta gratis '
                'y compáralos con tu prueba Pro de 14 días.',
                422,
                'ocr_required',
            )
    finally:
        doc.close()

    return data


def _snapshots(analysis: dict) -> list[dict]:
    return [
        {
            'stable_key': section['stable_key'],
            'heading': section['heading'],
            'body_hash': section['body_hash'],
            'normalized_text': section['normalized_text'],
            'bboxes': section['bboxes'],
            'order_index': section['order_index'],
        }
        for section in analysis['sections']
    ]


def build_result(bytes_a: bytes, bytes_b: bytes) -> dict:
    """analyze (no OCR) → compare → strip bboxes (useless without PDF panes)."""
    analysis_a = analyze_bytes(bytes_a, allow_ocr=False)
    analysis_b = analyze_bytes(bytes_b, allow_ocr=False)
    comparison = compare_snapshots(_snapshots(analysis_a), _snapshots(analysis_b))
    sections = [
        {key: value for key, value in diff.items()
         if key not in ('bboxes_from', 'bboxes_to')}
        for diff in comparison['diffs']
    ]
    return {
        'counts': comparison['counts'],
        'summary_text': comparison['summary_text'],
        'sections': sections,
        'meta': {
            'page_count_a': analysis_a['page_count'],
            'page_count_b': analysis_b['page_count'],
        },
    }


def create_public_comparison(file_a, file_b, ip: str) -> PublicComparison:
    bytes_a = validate_public_pdf(file_a)
    bytes_b = validate_public_pdf(file_b)

    comparison = PublicComparison.objects.create(
        file_a_name=Path(file_a.name or 'a.pdf').name[:255],
        file_b_name=Path(file_b.name or 'b.pdf').name[:255],
        expires_at=timezone.now()
        + timedelta(hours=settings.PUBLIC_COMPARE_TTL_HOURS),
        ip_hash=sha256(f'{ip}{settings.SECRET_KEY}'.encode()).hexdigest(),
    )
    storage_service.put_bytes(
        storage_key_for(comparison.public_id, 'a'), bytes_a, 'application/pdf'
    )
    storage_service.put_bytes(
        storage_key_for(comparison.public_id, 'b'), bytes_b, 'application/pdf'
    )

    from ..tasks import run_public_comparison

    run_public_comparison.apply_async(args=[comparison.pk], queue='engine_light')
    comparison.refresh_from_db()  # eager mode already finished the job
    return comparison


def delete_stored_files(comparison: PublicComparison) -> None:
    """Attempt both objects; report failure so callers retain the recovery row."""
    first_error: Exception | None = None
    for slot in ('a', 'b'):
        try:
            storage_service.delete(storage_key_for(comparison.public_id, slot))
        except Exception as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
