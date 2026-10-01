"""
Engine Celery tasks (docs/plan/05 §7 — AnalysisJob slice, It1).

Contract: the domain enqueues an EngineJob and consumes its `result`.
Idempotency by natural key (I15): a `done` job re-dispatched returns its
stored result without side effects. Each persisted phase confirms a private
checkpoint in the same transaction. Parse errors are PERMANENT (no retry,
C1-E04); infrastructure errors retry with backoff (3 retries).
"""

import logging

from celery import shared_task
from django.db import transaction

from documents.models import DocumentVersion
from documents.services import storage_service
from engine.models import EngineJob
from engine.services.analysis import EncryptedPdfError, InvalidPdfError, analyze_bytes
from engine.services.persistence import persist_analysis

logger = logging.getLogger(__name__)

PROGRESS_KEY = '_analysis_progress'
ANALYSIS_PHASES = ('analysis', 'checks', 'comparison', 'd5', 'reanchor')
RECOVERY_ERROR = (
    'No se puede reanudar este análisis antiguo sin un punto de recuperación verificado.'
)


class _RecoveryBlocked(Exception):
    """Existing data has no checkpoint that can safely authorize a replay."""


def enqueue_analysis(version: DocumentVersion) -> EngineJob:
    """Create (or reuse) the analysis job for a version and dispatch it."""
    job, created = EngineJob.objects.get_or_create(
        idempotency_key=f'analysis:v{version.pk}',
        defaults={
            'job_type': EngineJob.Type.ANALYSIS,
            'document_version': version,
            'payload': {'version_id': version.pk, 'file_key': version.file_key},
        },
    )
    if job.status == EngineJob.Status.DONE:
        return job
    async_result = run_analysis.apply_async(args=[job.pk], queue='engine_heavy')
    EngineJob.objects.filter(pk=job.pk).update(celery_task_id=async_result.id or '')
    job.refresh_from_db()
    return job


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def run_analysis(self, job_id: int):
    try:
        job = _begin_analysis(job_id)
    except Exception as exc:
        _action, result = _handle_failure(self, job_id, None, exc)
        return result
    if job.status == EngineJob.Status.DONE:
        return job.result
    if job.status == EngineJob.Status.FAILED:
        return None

    while True:
        phase = None
        try:
            with transaction.atomic():
                job = _locked_job(job_id)
                if job.status == EngineJob.Status.DONE:
                    return job.result
                version = _job_version(job)
                progress = _read_progress(job, version)
                phase = _next_phase(progress)
                if phase == 'finalize':
                    job.result = {
                        **progress['analysis_result'],
                        'comparison': progress['comparison_result'],
                    }
                    job.status = EngineJob.Status.DONE
                    job.error_detail = ''
                    job.save(update_fields=['result', 'status', 'error_detail', 'updated_at'])
                    return job.result
                if phase != 'analysis':
                    _complete_phase(job, version, progress, phase)
                    continue

            # Duplicate deliveries may parse; neither storage IO nor OCR holds
            # a job lock. Only the first delivery to confirm analysis persists it.
            data = storage_service.get_bytes(version.file_key)
            analysis = analyze_bytes(data)
            with transaction.atomic():
                job = _locked_job(job_id)
                if job.status == EngineJob.Status.DONE:
                    return job.result
                version = _job_version(job)
                if _read_progress(job, version) is not None:
                    continue
                result = persist_analysis(version, analysis)
                if not _valid_analysis_result(result, version):
                    raise _RecoveryBlocked
                _write_progress(job, {
                    'schema': 1,
                    'last_completed': 'analysis',
                    'analysis_result': result,
                    'comparison_pk': None,
                    'comparison_result': None,
                })
        except Exception as exc:
            action, result = _handle_failure(self, job_id, phase, exc)
            if action == 'resume':
                continue
            return result


def _locked_job(job_id: int) -> EngineJob:
    # Do not join versions here: the serialization boundary is this job alone.
    return EngineJob.objects.select_for_update().get(pk=job_id)


def _job_version(job: EngineJob) -> DocumentVersion:
    if job.job_type != EngineJob.Type.ANALYSIS or not job.document_version_id:
        raise _RecoveryBlocked
    try:
        return DocumentVersion.all_objects.select_related('document').get(
            pk=job.document_version_id
        )
    except DocumentVersion.DoesNotExist as exc:
        raise _RecoveryBlocked from exc


def _valid_analysis_result(result, version: DocumentVersion) -> bool:
    if not isinstance(result, dict) or set(result) != {
        'scenario', 'degraded', 'page_count', 'sections'
    }:
        return False
    if (
        result['scenario'] not in DocumentVersion.Scenario.values
        or result['scenario'] != version.source_scenario
        or type(result['degraded']) is not bool
        or type(result['page_count']) is not int
        or result['page_count'] < 0
        or result['page_count'] != version.page_count
    ):
        return False
    sections = result['sections']
    if not isinstance(sections, dict) or set(sections) != {
        'same', 'renamed', 'added', 'removed', 'total'
    }:
        return False
    if any(type(value) is not int or value < 0 for value in sections.values()):
        return False
    return sections['same'] + sections['renamed'] + sections['added'] == sections['total']


def _valid_comparison_result(result, version: DocumentVersion) -> bool:
    if not isinstance(result, dict) or set(result) != {'id', 'from', 'to', 'counts', 'text'}:
        return False
    if (
        not isinstance(result['id'], str)
        or not result['id']
        or type(result['from']) is not int
        or not 0 < result['from'] < version.number
        or type(result['to']) is not int
        or result['to'] != version.number
        or not isinstance(result['text'], str)
    ):
        return False
    counts = result['counts']
    return (
        isinstance(counts, dict)
        and set(counts) == {'unchanged', 'modified', 'added', 'removed', 'renamed_only'}
        and all(type(value) is int and value >= 0 for value in counts.values())
    )


def _checkpoint_comparison(progress: dict, version: DocumentVersion):
    from comparisons.models import Comparison

    try:
        comparison = Comparison.objects.get(
            pk=progress['comparison_pk'],
            document_id=version.document_id,
            to_version_id=version.pk,
            status=Comparison.Status.DONE,
        )
    except Comparison.DoesNotExist as exc:
        raise _RecoveryBlocked from exc
    if progress['comparison_result'] != _comparison_result(comparison, version):
        raise _RecoveryBlocked
    return comparison


def _read_progress(job: EngineJob, version: DocumentVersion) -> dict | None:
    payload = job.payload
    if (
        not isinstance(payload, dict)
        or type(payload.get('version_id')) is not int
        or payload['version_id'] != version.pk
        or payload.get('file_key') != version.file_key
        or job.result is not None
    ):
        raise _RecoveryBlocked
    if PROGRESS_KEY not in payload:
        if (
            version.analysis_status == DocumentVersion.AnalysisStatus.READY
            or version.section_versions.exists()
        ):
            raise _RecoveryBlocked
        return None

    progress = payload[PROGRESS_KEY]
    if (
        not isinstance(progress, dict)
        or set(progress) != {
            'schema', 'last_completed', 'analysis_result', 'comparison_pk', 'comparison_result'
        }
        or type(progress['schema']) is not int
        or progress['schema'] != 1
        or progress['last_completed'] not in ANALYSIS_PHASES
        or version.analysis_status != DocumentVersion.AnalysisStatus.READY
        or not _valid_analysis_result(progress['analysis_result'], version)
    ):
        raise _RecoveryBlocked

    comparison_pk = progress['comparison_pk']
    comparison_result = progress['comparison_result']
    if ANALYSIS_PHASES.index(progress['last_completed']) < ANALYSIS_PHASES.index('comparison'):
        if comparison_pk is not None or comparison_result is not None:
            raise _RecoveryBlocked
    elif comparison_pk is None:
        if comparison_result is not None:
            raise _RecoveryBlocked
    else:
        if (
            type(comparison_pk) is not int
            or comparison_pk <= 0
            or not _valid_comparison_result(comparison_result, version)
        ):
            raise _RecoveryBlocked
        _checkpoint_comparison(progress, version)
    return progress


def _next_phase(progress: dict | None) -> str:
    if progress is None:
        return 'analysis'
    next_index = ANALYSIS_PHASES.index(progress['last_completed']) + 1
    return ANALYSIS_PHASES[next_index] if next_index < len(ANALYSIS_PHASES) else 'finalize'


def _write_progress(job: EngineJob, progress: dict):
    job.payload = {**job.payload, PROGRESS_KEY: progress}
    job.status = EngineJob.Status.RUNNING
    job.save(update_fields=['payload', 'status', 'updated_at'])


@transaction.atomic
def _begin_analysis(job_id: int) -> EngineJob:
    job = _locked_job(job_id)
    if job.status == EngineJob.Status.DONE:
        return job
    try:
        version = _job_version(job)
        progress = _read_progress(job, version)
    except _RecoveryBlocked:
        _fail(job, None, RECOVERY_ERROR, fail_version=False)
        return job
    job.status = EngineJob.Status.RUNNING
    job.attempts += 1
    job.save(update_fields=['status', 'attempts', 'updated_at'])
    if progress is None:
        DocumentVersion.all_objects.filter(pk=version.pk).update(
            analysis_status=DocumentVersion.AnalysisStatus.PROCESSING
        )
    return job


def _complete_phase(job: EngineJob, version: DocumentVersion, progress: dict, phase: str):
    progress = progress.copy()
    if phase == 'checks':
        from checks.services import run_checks

        run_checks(version)
    elif phase == 'comparison':
        comparison = _build_auto_comparison(version)
        progress['comparison_pk'] = comparison.pk if comparison is not None else None
        progress['comparison_result'] = (
            _comparison_result(comparison, version) if comparison is not None else None
        )
    elif phase == 'd5' and progress['comparison_pk'] is not None:
        from reviews.services.seal_service import apply_invalidation

        apply_invalidation(_checkpoint_comparison(progress, version))
    elif phase == 'reanchor' and progress['comparison_pk'] is not None:
        from observations.services import reanchor_observations

        reanchor_observations(version)
    progress['last_completed'] = phase
    _write_progress(job, progress)


def _handle_failure(self, job_id: int, phase: str | None, exc: Exception):
    action, result = _record_failure(
        job_id, phase, exc, self.request.retries >= self.max_retries
    )
    if action in ('retry', 'failed'):
        logger.exception('Analysis job %s failed in phase %s', job_id, phase or 'entry')
    if action == 'retry':
        # _record_failure has released its transaction and lock before Celery.
        raise self.retry(exc=exc)
    return action, result


@transaction.atomic
def _record_failure(job_id: int, phase: str | None, exc: Exception, exhausted: bool):
    job = _locked_job(job_id)
    if job.status == EngineJob.Status.DONE:
        return 'return', job.result
    try:
        version = _job_version(job)
        progress = _read_progress(job, version)
    except _RecoveryBlocked:
        _fail(job, None, RECOVERY_ERROR, fail_version=False)
        return 'return', None

    if (
        progress is not None
        and phase in ANALYSIS_PHASES
        and ANALYSIS_PHASES.index(progress['last_completed']) >= ANALYSIS_PHASES.index(phase)
    ):
        return 'resume', None
    if isinstance(exc, _RecoveryBlocked):
        _fail(job, None, RECOVERY_ERROR, fail_version=False)
        return 'return', None
    if phase == 'analysis' and isinstance(exc, (EncryptedPdfError, InvalidPdfError)):
        _fail(job, version, f'Documento inválido: {exc}')
        return 'return', None
    if exhausted:
        _fail(
            job, version, f'Error de análisis tras reintentos: {exc}',
            fail_version=progress is None,
        )
        return 'failed', None
    return 'retry', None


def _build_auto_comparison(version: DocumentVersion):
    """C2: compare against the previous analyzed version as soon as the new one
    is ready — the editor sees what changed without asking (docs/plan/05 §2)."""
    from comparisons.services import build_comparison

    previous = (
        DocumentVersion.objects.filter(
            document=version.document,
            number__lt=version.number,
            analysis_status=DocumentVersion.AnalysisStatus.READY,
        )
        .order_by('-number')
        .first()
    )
    if previous is None:
        return None
    from comparisons.models import Comparison

    return build_comparison(
        version.document, previous, version, version.author,
        trigger=Comparison.Trigger.AUTO,
    )


def _comparison_result(comparison, version: DocumentVersion) -> dict:
    return {
        'id': str(comparison.public_id),
        'from': comparison.from_version.number,
        'to': version.number,
        'counts': comparison.summary.get('counts', {}),
        'text': comparison.summary.get('text', ''),
    }


def _fail(
    job: EngineJob, version: DocumentVersion | None, detail: str, *, fail_version: bool = True
):
    job.status = EngineJob.Status.FAILED
    job.error_detail = detail[:1000]
    job.save(update_fields=['status', 'error_detail', 'updated_at'])
    if fail_version and version is not None:
        DocumentVersion.all_objects.filter(pk=version.pk).update(
            analysis_status=DocumentVersion.AnalysisStatus.FAILED, error_detail=detail[:1000]
        )
