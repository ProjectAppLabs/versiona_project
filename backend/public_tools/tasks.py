"""Async processing + TTL cleanup for anonymous public comparisons."""

import logging

from celery import shared_task
from django.utils import timezone

from documents.services import storage_service
from engine.services.analysis import OcrRequiredError

from .models import PublicComparison

logger = logging.getLogger(__name__)

PUBLIC_COMPARISON_PURGE_BATCH_SIZE = 100


@shared_task(name='public_tools.tasks.run_public_comparison', soft_time_limit=120)
def run_public_comparison(comparison_pk: int) -> None:
    from .services.public_comparison_service import build_result, delete_stored_files
    from .services.public_comparison_service import storage_key_for

    try:
        comparison = PublicComparison.objects.get(pk=comparison_pk)
    except PublicComparison.DoesNotExist:
        return
    if comparison.status == PublicComparison.Status.DONE:
        return

    comparison.status = PublicComparison.Status.PROCESSING
    comparison.save(update_fields=['status'])
    phase = 'read_a'
    try:
        bytes_a = storage_service.get_bytes(storage_key_for(comparison.public_id, 'a'))
        phase = 'read_b'
        bytes_b = storage_service.get_bytes(storage_key_for(comparison.public_id, 'b'))
        phase = 'build_result'
        comparison.result = build_result(bytes_a, bytes_b)
        comparison.status = PublicComparison.Status.DONE
        phase = 'persist_result'
        comparison.save(update_fields=['result', 'status'])
    except OcrRequiredError:
        comparison.status = PublicComparison.Status.FAILED
        comparison.error_code = 'ocr_required'
        comparison.save(update_fields=['status', 'error_code'])
    except Exception as exc:
        logger.error(
            'Public comparison processing failed: phase=%s error_class=%s',
            phase, type(exc).__name__,
            extra={'phase': phase, 'error_class': type(exc).__name__},
        )
        comparison.status = PublicComparison.Status.FAILED
        comparison.error_code = 'processing_failed'
        comparison.save(update_fields=['status', 'error_code'])
    finally:
        try:
            delete_stored_files(comparison)
        except Exception as exc:
            # Keep status/result and public_id: the TTL sweep can retry both
            # keys, including a sibling already deleted by this attempt.
            logger.warning(
                'Public comparison cleanup deferred: phase=processing_cleanup error_class=%s',
                type(exc).__name__,
                extra={'phase': 'processing_cleanup', 'error_class': type(exc).__name__},
            )


@shared_task(name='public_tools.tasks.purge_expired_public_comparisons')
def purge_expired_public_comparisons() -> int:
    from .services.public_comparison_service import delete_stored_files

    expired = PublicComparison.objects.filter(expires_at__lt=timezone.now())
    last_pk = 0
    purged = 0
    while batch := list(
        expired.filter(pk__gt=last_pk).order_by('pk').only('pk', 'public_id')[
            :PUBLIC_COMPARISON_PURGE_BATCH_SIZE
        ]
    ):
        last_pk = batch[-1].pk
        for comparison in batch:
            try:
                delete_stored_files(comparison)  # covers workers that died mid-job
            except Exception as exc:
                logger.warning(
                    'Public comparison cleanup deferred: phase=expired_purge error_class=%s',
                    type(exc).__name__,
                    extra={'phase': 'expired_purge', 'error_class': type(exc).__name__},
                )
                continue  # retain the keys for the next sweep, advance this one
            comparison.delete()
            purged += 1
    return purged
