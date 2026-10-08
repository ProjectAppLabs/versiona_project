"""Engine task idempotency, parse failures, and infrastructure retries."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import patch

import pytest
from checks import services as check_services
from checks.models import CheckRun
from comparisons import services as comparison_services
from comparisons.models import Comparison
from documents.models import Document, DocumentVersion, SectionVersion
from observations import services as observation_services
from observations.models import ObservationAnchor
from reviews.models import SealValidityRecord
from reviews.services import seal_service

from engine import tasks as task_module
from engine.models import EngineJob
from engine.tasks import PROGRESS_KEY, enqueue_analysis, run_analysis

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


def load(name: str) -> bytes:
    """Load one deterministic PDF fixture by name."""
    return (TESTDATA / name).read_bytes()


@pytest.fixture
def pending_version_factory(versiona_context):
    """Create pending document versions inside the shared engine context."""
    def _make(document=None):
        if document is None:
            document = Document.objects.create(
                project=versiona_context.project,
                title='Contrato del motor',
                slug='contrato-del-motor',
            )
        number = document.latest_number + 1
        version = DocumentVersion.objects.create(
            document=document,
            number=number,
            sha256=f'{number:064d}',
            file_key=f'test/engine/{document.public_id}/v{number}/original.pdf',
            analysis_status=DocumentVersion.AnalysisStatus.PENDING,
            config_version=versiona_context.config,
            author=versiona_context.users['editor'],
        )
        document.latest_number = number
        document.save(update_fields=['latest_number'])
        return version

    return _make


@pytest.fixture
def version(pending_version_factory):
    """Create a pending document version for a task test."""
    return pending_version_factory()


@pytest.fixture
def make_job(version):
    """Create analysis jobs for the pending test version."""
    def _make(**overrides):
        fields = {
            'job_type': EngineJob.Type.ANALYSIS,
            'document_version': version,
            'payload': {'version_id': version.pk, 'file_key': version.file_key},
            'idempotency_key': f'analysis:v{version.pk}',
            'status': EngineJob.Status.PENDING,
        }
        fields.update(overrides)
        return EngineJob.objects.create(**fields)

    return _make


def _run_with_pdf(job, filename):
    with patch('engine.tasks.storage_service.get_bytes', return_value=load(filename)):
        return run_analysis(job.pk)


def _job_for(version):
    return EngineJob.objects.create(
        job_type=EngineJob.Type.ANALYSIS,
        document_version=version,
        payload={'version_id': version.pk, 'file_key': version.file_key},
        idempotency_key=f'analysis:v{version.pk}',
        status=EngineJob.Status.PENDING,
    )


def _prepared_redelivery(versiona_context, pending_version_factory):
    versiona_context.config.checklist = [{
        'key': 'contract-reference',
        'label': 'Referencia contractual',
        'type': 'required_text',
        'param': 'contrato',
    }]
    versiona_context.config.save(update_fields=['checklist'])
    previous = pending_version_factory()
    _run_with_pdf(_job_for(previous), 'contrato_v1.pdf')
    previous.refresh_from_db()
    seal_service.create_seal(
        previous,
        versiona_context.users['reviewer'],
        section_keys=['obligaciones-del-contratista'],
    )
    observation_services.create_observation(
        previous,
        versiona_context.users['reviewer'],
        body='Conservar el objeto contractual.',
        section_key='objeto-del-contrato',
    )
    current = pending_version_factory(document=previous.document)
    return previous, current, _job_for(current)


@pytest.mark.django_db
def test_current_degraded_analysis_requires_coordinator(versiona_context, pending_version_factory):
    _previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)

    _run_with_pdf(job, 'sin_encabezados.pdf')

    job.refresh_from_db()
    record = SealValidityRecord.objects.get(to_document_version=current)
    assert job.result['degraded'] is True
    assert record.decision == SealValidityRecord.Decision.PENDING


@pytest.mark.django_db
def test_previous_done_degradation_requires_coordinator(versiona_context, pending_version_factory):
    previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    previous_job = EngineJob.objects.get(document_version=previous)
    previous_job.result['degraded'] = True
    previous_job.save(update_fields=['result'])

    _run_with_pdf(job, 'contrato_v2.pdf')

    assert SealValidityRecord.objects.get(to_document_version=current).decision == SealValidityRecord.Decision.PENDING


@pytest.mark.django_db
def test_previous_checkpoint_degradation_requires_coordinator(versiona_context, pending_version_factory):
    previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    previous_job = EngineJob.objects.get(document_version=previous)
    previous_job.result = None
    previous_job.status = EngineJob.Status.RUNNING
    previous_job.payload[PROGRESS_KEY]['analysis_result']['degraded'] = True
    previous_job.save(update_fields=['result', 'status', 'payload'])

    _run_with_pdf(job, 'contrato_v2.pdf')

    assert SealValidityRecord.objects.get(to_document_version=current).decision == SealValidityRecord.Decision.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize('invalid_flag', ['true', 1, None])
def test_malformed_previous_degradation_keeps_legacy_fallback(
    versiona_context, pending_version_factory, invalid_flag,
):
    previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    previous_job = EngineJob.objects.get(document_version=previous)
    previous_job.result['degraded'] = invalid_flag
    previous_job.save(update_fields=['result'])

    _run_with_pdf(job, 'contrato_v2.pdf')

    record = SealValidityRecord.objects.get(to_document_version=current)
    assert record.decided_mode == SealValidityRecord.Mode.AUTO
    assert record.decision == SealValidityRecord.Decision.INVALIDATED


@pytest.mark.django_db
def test_missing_previous_analysis_keeps_legacy_fallback(versiona_context, pending_version_factory):
    previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    EngineJob.objects.filter(document_version=previous).delete()

    _run_with_pdf(job, 'contrato_v2.pdf')

    assert SealValidityRecord.objects.get(to_document_version=current).decided_mode == SealValidityRecord.Mode.AUTO


@pytest.mark.django_db
def test_degraded_d5_retry_preserves_coordinator_decision(versiona_context, pending_version_factory):
    _previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    calls = 0

    # Simulate a transient phase failure, retaining the existing recovery test idiom.
    original = seal_service.apply_invalidation

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 1:
            raise RuntimeError('d5 unavailable')
        return result

    with patch('reviews.services.seal_service.apply_invalidation', side_effect=interrupted):
        with pytest.raises(RuntimeError, match='d5 unavailable'):
            _run_with_pdf(job, 'sin_encabezados.pdf')
    _run_with_pdf(job, 'sin_encabezados.pdf')

    record = SealValidityRecord.objects.get(to_document_version=current)
    assert record.decision == SealValidityRecord.Decision.PENDING
    assert record.decided_mode == SealValidityRecord.Mode.COORDINATOR


@pytest.mark.django_db
@pytest.mark.escenario('C1-A04')
def test_enqueue_analysis_returns_the_done_job_without_redispatch(version, make_job):
    """Return an existing completed job without dispatching another task."""
    job = make_job(status=EngineJob.Status.DONE, result={'sections': {'total': 1}})

    returned = enqueue_analysis(version)

    assert returned.pk == job.pk
    assert returned.celery_task_id == ''
    assert EngineJob.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('C1-A05')
def test_run_analysis_returns_the_stored_result_for_a_done_job(make_job):
    """Return the stored result without incrementing a completed job attempt."""
    job = make_job(status=EngineJob.Status.DONE, result={'cached': True})

    result = run_analysis(job.pk)

    assert result == {'cached': True}
    job.refresh_from_db()
    assert job.attempts == 0


@pytest.mark.django_db
@pytest.mark.escenario('C1-E02')
def test_run_analysis_marks_a_corrupt_pdf_as_permanent_failure(version, make_job):
    """Mark the job and version failed when PDF parsing finds corrupt input."""
    job = make_job()

    with patch('engine.tasks.storage_service.get_bytes', return_value=load('corrupto.pdf')):
        result = run_analysis(job.pk)

    assert result is None
    job.refresh_from_db()
    assert job.status == EngineJob.Status.FAILED
    assert job.error_detail.startswith('Documento inválido:')
    version.refresh_from_db()
    assert version.analysis_status == DocumentVersion.AnalysisStatus.FAILED


@pytest.mark.django_db
@pytest.mark.escenario('C1-E01')
def test_run_analysis_marks_an_encrypted_pdf_as_permanent_failure(version, make_job):
    """Mark an encrypted PDF job failed without retrying the parse error."""
    job = make_job()

    with patch('engine.tasks.storage_service.get_bytes', return_value=load('protegido.pdf')):
        result = run_analysis(job.pk)

    assert result is None
    job.refresh_from_db()
    assert job.status == EngineJob.Status.FAILED
    assert job.error_detail.startswith('Documento inválido:')


@pytest.mark.django_db
@pytest.mark.escenario('C1-E05')
def test_run_analysis_requests_a_retry_on_infrastructure_error(version, make_job):
    """Keep the job running while an infrastructure failure requests retry."""
    job = make_job()

    with patch('engine.tasks.storage_service.get_bytes', side_effect=RuntimeError('minio caído')):
        with pytest.raises(RuntimeError):
            run_analysis(job.pk)

    job.refresh_from_db()
    assert job.status == EngineJob.Status.RUNNING
    assert job.attempts == 1


@pytest.mark.django_db
@pytest.mark.escenario('C1-E05')
def test_run_analysis_fails_permanently_after_exhausting_retries(version, make_job):
    """Fail the job and version after infrastructure retries are exhausted."""
    job = make_job()

    with patch('engine.tasks.storage_service.get_bytes', side_effect=RuntimeError('minio caído')):
        outcome = run_analysis.apply(args=[job.pk], retries=3)

    assert outcome.result is None
    job.refresh_from_db()
    assert job.status == EngineJob.Status.FAILED
    assert job.error_detail.startswith('Error de análisis tras reintentos')
    version.refresh_from_db()
    assert version.analysis_status == DocumentVersion.AnalysisStatus.FAILED


@pytest.mark.django_db
@pytest.mark.escenario('C1-E05')
def test_run_analysis_keeps_checkpoints_private_until_the_redelivery_finishes(
    client_as, pending_version_factory, versiona_context
):
    """Fails if a completed phase leaks progress publicly or the retry repeats snapshots."""
    _previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    real_run_checks = check_services.run_checks
    calls = 0

    def fail_once(version):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('check worker unavailable')
        return real_run_checks(version)

    with patch('checks.services.run_checks', side_effect=fail_once):
        with patch('engine.tasks.storage_service.get_bytes', return_value=load('contrato_v2.pdf')):
            with pytest.raises(RuntimeError):
                run_analysis(job.pk)

    job.refresh_from_db()
    assert job.status == EngineJob.Status.RUNNING
    assert job.result is None
    assert set(job.payload) == {'version_id', 'file_key', PROGRESS_KEY}
    assert job.payload[PROGRESS_KEY]['schema'] == 1
    assert job.payload[PROGRESS_KEY]['last_completed'] == 'analysis'
    assert SectionVersion.objects.filter(document_version=current).count() == 9
    polling = client_as('viewer').get(f'/api/jobs/{job.public_id}/')
    assert polling.status_code == 200
    assert polling.data['status'] == EngineJob.Status.RUNNING
    assert polling.data['error'] is None
    assert polling.data['result'] is None

    _run_with_pdf(job, 'contrato_v2.pdf')

    job.refresh_from_db()
    assert job.status == EngineJob.Status.DONE
    assert set(job.result) == {'scenario', 'degraded', 'page_count', 'sections', 'comparison'}
    assert job.result['comparison']['from'] == 1
    assert job.result['comparison']['to'] == 2
    assert SectionVersion.objects.filter(document_version=current).count() == 9
    assert CheckRun.objects.filter(document_version=current).count() == 1
    assert Comparison.objects.filter(to_version=current).count() == 1
    assert SealValidityRecord.objects.filter(to_document_version=current).count() == 1
    assert ObservationAnchor.objects.filter(document_version=current).count() == 1


@pytest.mark.django_db
def test_run_analysis_rolls_back_snapshots_when_checkpoint_write_fails(
    pending_version_factory
):
    """Fails if analysis snapshots commit without their private recovery checkpoint."""
    current = pending_version_factory()
    job = _job_for(current)

    with patch('engine.tasks._write_progress', side_effect=RuntimeError('checkpoint unavailable')):
        with patch('engine.tasks.storage_service.get_bytes', return_value=load('contrato_v1.pdf')):
            with pytest.raises(RuntimeError):
                run_analysis(job.pk)

    job.refresh_from_db()
    current.refresh_from_db()
    assert job.status == EngineJob.Status.RUNNING
    assert PROGRESS_KEY not in job.payload
    assert job.result is None
    assert current.analysis_status == DocumentVersion.AnalysisStatus.PROCESSING
    assert SectionVersion.objects.filter(document_version=current).count() == 0


@pytest.mark.django_db
def test_run_analysis_exhaustion_after_a_checkpoint_preserves_the_ready_version(
    pending_version_factory, versiona_context
):
    """Fails if retry exhaustion after analysis marks an immutable ready version failed."""
    versiona_context.config.checklist = [{
        'key': 'contract-reference',
        'label': 'Referencia contractual',
        'type': 'required_text',
        'param': 'contrato',
    }]
    versiona_context.config.save(update_fields=['checklist'])
    current = pending_version_factory()
    job = _job_for(current)

    with patch('checks.services.run_checks', side_effect=RuntimeError('check worker unavailable')):
        with patch('engine.tasks.storage_service.get_bytes', return_value=load('contrato_v1.pdf')):
            outcome = run_analysis.apply(args=[job.pk], retries=3)

    assert outcome.result is None
    job.refresh_from_db()
    current.refresh_from_db()
    assert job.status == EngineJob.Status.FAILED
    assert job.error_detail.startswith('Error de análisis tras reintentos')
    assert current.analysis_status == DocumentVersion.AnalysisStatus.READY
    assert current.error_detail == ''
    assert job.payload[PROGRESS_KEY]['last_completed'] == 'analysis'
    assert SectionVersion.objects.filter(document_version=current).count() == 9


@pytest.mark.django_db
def test_run_analysis_resumes_a_failed_job_with_a_valid_checkpoint(
    pending_version_factory, versiona_context
):
    """Fails if a failed delivery with a verified checkpoint restarts immutable analysis."""
    _previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)

    with patch('checks.services.run_checks', side_effect=RuntimeError('check worker unavailable')):
        with patch('engine.tasks.storage_service.get_bytes', return_value=load('contrato_v2.pdf')):
            with pytest.raises(RuntimeError):
                run_analysis(job.pk)

    EngineJob.objects.filter(pk=job.pk).update(status=EngineJob.Status.FAILED)
    _run_with_pdf(job, 'contrato_v2.pdf')

    job.refresh_from_db()
    assert job.status == EngineJob.Status.DONE
    assert SectionVersion.objects.filter(document_version=current).count() == 9
    assert CheckRun.objects.filter(document_version=current).count() == 1
    assert Comparison.objects.filter(to_version=current).count() == 1


@pytest.mark.django_db
def test_run_analysis_blocks_a_legacy_ready_version_without_a_checkpoint(pending_version_factory):
    """Fails if a legacy ready snapshot can be replayed without durable recovery evidence."""
    current = pending_version_factory()
    initial = _job_for(current)
    _run_with_pdf(initial, 'contrato_v1.pdf')
    legacy = EngineJob.objects.create(
        job_type=EngineJob.Type.ANALYSIS,
        document_version=current,
        payload={'version_id': current.pk, 'file_key': current.file_key},
        idempotency_key=f'legacy:v{current.pk}',
        status=EngineJob.Status.PENDING,
    )
    snapshots_before = SectionVersion.objects.filter(document_version=current).count()

    result = run_analysis(legacy.pk)

    legacy.refresh_from_db()
    assert result is None
    assert legacy.status == EngineJob.Status.FAILED
    assert legacy.error_detail == 'No se puede reanudar este análisis antiguo sin un punto de recuperación verificado.'
    assert SectionVersion.objects.filter(document_version=current).count() == snapshots_before


@pytest.mark.django_db
@pytest.mark.parametrize(
    'progress',
    [
        {'schema': 2, 'last_completed': 'analysis', 'analysis_result': {}, 'comparison_pk': None, 'comparison_result': None},
        {'schema': 1, 'last_completed': 'unknown', 'analysis_result': {}, 'comparison_pk': None, 'comparison_result': None},
        {'schema': 1, 'last_completed': 'analysis', 'analysis_result': [], 'comparison_pk': None, 'comparison_result': None},
    ],
    ids=['schema', 'phase', 'summary'],
)
def test_run_analysis_blocks_an_invalid_checkpoint(progress, pending_version_factory):
    """Fails if malformed recovery metadata authorizes a replay of an analyzed version."""
    current = pending_version_factory()
    DocumentVersion.all_objects.filter(pk=current.pk).update(
        analysis_status=DocumentVersion.AnalysisStatus.READY
    )
    job = EngineJob.objects.create(
        job_type=EngineJob.Type.ANALYSIS,
        document_version=current,
        payload={
            'version_id': current.pk,
            'file_key': current.file_key,
            PROGRESS_KEY: progress,
        },
        idempotency_key=f'invalid:v{current.pk}',
        status=EngineJob.Status.PENDING,
    )

    result = run_analysis(job.pk)

    job.refresh_from_db()
    assert result is None
    assert job.status == EngineJob.Status.FAILED
    assert job.error_detail == 'No se puede reanudar este análisis antiguo sin un punto de recuperación verificado.'
    assert SectionVersion.objects.filter(document_version=current).count() == 0


@pytest.mark.django_db
def test_run_analysis_blocks_a_checkpoint_when_its_version_is_not_ready(pending_version_factory):
    """Fails if recovery metadata authorizes work before analysis has made the version ready."""
    current = pending_version_factory()
    job = EngineJob.objects.create(
        job_type=EngineJob.Type.ANALYSIS,
        document_version=current,
        payload={
            'version_id': current.pk,
            'file_key': current.file_key,
            PROGRESS_KEY: {
                'schema': 1,
                'last_completed': 'analysis',
                'analysis_result': {
                    'scenario': DocumentVersion.Scenario.TEXT_NATIVE,
                    'degraded': False,
                    'page_count': 0,
                    'sections': {'same': 0, 'renamed': 0, 'added': 0, 'removed': 0, 'total': 0},
                },
                'comparison_pk': None,
                'comparison_result': None,
            },
        },
        idempotency_key=f'non-ready:v{current.pk}',
        status=EngineJob.Status.PENDING,
    )

    result = run_analysis(job.pk)

    job.refresh_from_db()
    current.refresh_from_db()
    assert result is None
    assert job.status == EngineJob.Status.FAILED
    assert job.error_detail == 'No se puede reanudar este análisis antiguo sin un punto de recuperación verificado.'
    assert current.analysis_status == DocumentVersion.AnalysisStatus.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('phase', 'patch_target', 'service'),
    [
        ('checks', 'checks.services.run_checks', check_services.run_checks),
        ('comparison', 'comparisons.services.build_comparison', comparison_services.build_comparison),
        ('d5', 'reviews.services.seal_service.apply_invalidation', seal_service.apply_invalidation),
        ('reanchor', 'observations.services.reanchor_observations', observation_services.reanchor_observations),
    ],
)
def test_run_analysis_resumes_after_a_completed_phase_service_fails_once(
    phase, patch_target, service, pending_version_factory, versiona_context
):
    """Fails if retrying one derived phase duplicates already checkpointed engine effects."""
    _previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = service(*args, **kwargs)
        if calls == 1:
            raise RuntimeError(f'{phase} unavailable')
        return result

    with patch(patch_target, side_effect=fail_once):
        with patch('engine.tasks.storage_service.get_bytes', return_value=load('contrato_v2.pdf')):
            with pytest.raises(RuntimeError):
                run_analysis(job.pk)

    job.refresh_from_db()
    assert job.result is None
    assert job.payload[PROGRESS_KEY]['last_completed'] != phase
    _run_with_pdf(job, 'contrato_v2.pdf')

    job.refresh_from_db()
    assert job.status == EngineJob.Status.DONE
    assert SectionVersion.objects.filter(document_version=current).count() == 9
    assert CheckRun.objects.filter(document_version=current).count() == 1
    assert Comparison.objects.filter(to_version=current).count() == 1
    assert SealValidityRecord.objects.filter(to_document_version=current).count() == 1
    assert ObservationAnchor.objects.filter(document_version=current).count() == 1


@pytest.mark.django_db
def test_run_analysis_retries_finalization_without_publishing_a_partial_result(
    pending_version_factory, versiona_context
):
    """Fails if a final-result write failure exposes a completed public response early."""
    _previous, current, job = _prepared_redelivery(versiona_context, pending_version_factory)
    original_save = EngineJob.save
    calls = 0

    def fail_done_save(instance, *args, **kwargs):
        nonlocal calls
        if instance.pk == job.pk and instance.status == EngineJob.Status.DONE and calls == 0:
            calls += 1
            raise RuntimeError('result store unavailable')
        return original_save(instance, *args, **kwargs)

    with patch.object(EngineJob, 'save', new=fail_done_save):
        with patch('engine.tasks.storage_service.get_bytes', return_value=load('contrato_v2.pdf')):
            with pytest.raises(RuntimeError):
                run_analysis(job.pk)

    job.refresh_from_db()
    assert job.status == EngineJob.Status.RUNNING
    assert job.result is None
    _run_with_pdf(job, 'contrato_v2.pdf')

    job.refresh_from_db()
    assert job.status == EngineJob.Status.DONE
    assert set(job.result) == {'scenario', 'degraded', 'page_count', 'sections', 'comparison'}


@pytest.mark.django_db(transaction=True)
def test_run_analysis_keeps_winner_state_when_a_duplicate_delivery_fails_late(
    pending_version_factory
):
    """Fails if a second MySQL delivery can overwrite the winner after its analysis checkpoint."""
    current = pending_version_factory()
    job = _job_for(current)
    barrier = Barrier(2)
    checkpoint_written = Event()
    order = Lock()
    callers = 0
    original_write_progress = task_module._write_progress

    def record_checkpoint(engine_job, progress):
        original_write_progress(engine_job, progress)
        if progress['last_completed'] == 'analysis':
            checkpoint_written.set()

    def delivery_bytes(_file_key):
        nonlocal callers
        barrier.wait(timeout=20)
        with order:
            callers += 1
            position = callers
        if position == 1:
            return load('contrato_v1.pdf')
        checkpoint_written.wait(timeout=60)
        raise RuntimeError('late storage failure')

    def deliver():
        from django.db import close_old_connections

        close_old_connections()
        try:
            return run_analysis(job.pk)
        finally:
            close_old_connections()

    with patch('engine.tasks.storage_service.get_bytes', side_effect=delivery_bytes):
        with patch('engine.tasks._write_progress', side_effect=record_checkpoint):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(deliver)
                second = executor.submit(deliver)
                results = [first.result(), second.result()]

    job.refresh_from_db()
    assert results[0] == results[1]
    assert job.status == EngineJob.Status.DONE
    assert job.error_detail == ''
    assert SectionVersion.objects.filter(document_version=current).count() == 9
    assert CheckRun.objects.filter(document_version=current).count() == 0
    assert Comparison.objects.filter(to_version=current).count() == 0
