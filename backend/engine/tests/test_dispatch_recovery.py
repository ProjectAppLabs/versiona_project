"""Durable analysis intentions recover without repeating acknowledged publication."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import NAMESPACE_URL, uuid5

import pytest
from django.db import close_old_connections, transaction
from django.utils import timezone
from documents.models import Document, DocumentVersion
from freezegun import freeze_time
from kombu.exceptions import OperationalError
from notifications.models import Notification
from reviews.models import SealValidityRecord
from reviews.services import seal_service

from engine import tasks
from engine.models import EngineJob

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'
# Past the recovery threshold (at least 15 minutes, docs/plan/05 §7).
STALLED_FOR = timedelta(minutes=21)
STALLED_ERROR = 'El análisis se interrumpió varias veces y no pudo completarse.'


class _WorkerKilled(BaseException):
    """Stands in for SIGKILL: escapes every `except Exception` recovery path."""


@pytest.fixture
def analysis_job_factory(versiona_context):
    """Create isolated pending analysis intentions with eligible timestamps."""
    def create(**overrides):
        document = Document.objects.create(
            project=versiona_context.project, title='Pendiente', slug=f'pending-{EngineJob.objects.count()}',
        )
        version = DocumentVersion.objects.create(
            document=document, number=1, sha256='a' * 64, file_key=f'test/{document.public_id}.pdf',
            config_version=versiona_context.config, author=versiona_context.users['editor'],
        )
        fields = {
            'job_type': EngineJob.Type.ANALYSIS, 'document_version': version,
            'idempotency_key': f'analysis:v{version.pk}',
            'payload': {'version_id': version.pk, 'file_key': version.file_key},
        }
        fields.update(overrides)
        job = EngineJob.objects.create(**fields)
        EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(seconds=61))
        return job
    return create


@pytest.fixture
def broker(monkeypatch, settings):
    """Simulate the broker publication boundary without network access."""
    settings.CELERY_TASK_ALWAYS_EAGER = False
    connection = MagicMock()
    connection.__enter__.return_value = connection
    producer = connection.Producer.return_value
    producer.__enter__.return_value = producer
    connect = MagicMock(return_value=connection)
    publish = MagicMock()
    monkeypatch.setattr(tasks.run_analysis.app, 'connection_for_write', connect)
    monkeypatch.setattr(tasks.run_analysis, 'apply_async', publish)
    return SimpleNamespace(connect=connect, publish=publish, producer=producer)


@pytest.mark.django_db
def test_broker_failure_keeps_an_unpublished_intention(analysis_job_factory, broker, caplog):
    """Broker failure keeps an unpublished intention."""
    job = analysis_job_factory()
    broker.publish.side_effect = OperationalError('redis://private-password@internal-host')

    outcome = tasks._dispatch_pending_analysis(job.pk)

    job.refresh_from_db()
    assert outcome == 'deferred'
    assert job.status == EngineJob.Status.PENDING
    assert job.celery_task_id == ''
    assert job.error_detail == tasks.DISPATCH_ERROR
    assert 'private-password' not in caplog.text
    assert 'phase=publish error_class=OperationalError' in caplog.text


@pytest.mark.django_db
def test_recovery_publishes_the_existing_job(analysis_job_factory, broker):
    """Recovery publishes the existing job."""
    job = analysis_job_factory(error_detail=tasks.DISPATCH_ERROR)

    published = tasks.recover_pending_analysis()

    job.refresh_from_db()
    assert published == 1
    assert job.celery_task_id == str(uuid5(NAMESPACE_URL, f'urn:versiona:analysis:{job.public_id}'))
    assert job.error_detail == ''
    assert EngineJob.objects.count() == 1


@pytest.mark.django_db
def test_publisher_uses_local_bounded_transport(analysis_job_factory, broker):
    """Publisher uses local bounded transport."""
    job = analysis_job_factory()

    tasks._dispatch_pending_analysis(job.pk)

    assert broker.connect.call_args.kwargs['connect_timeout'] == 5
    options = broker.connect.call_args.kwargs['transport_options']
    assert {key: options[key] for key in (
        'socket_connect_timeout', 'socket_timeout', 'retry_on_timeout', 'max_retries',
    )} == {'socket_connect_timeout': 5, 'socket_timeout': 5, 'retry_on_timeout': False, 'max_retries': 0}
    assert broker.publish.call_args.kwargs == {
        'args': [job.pk], 'task_id': str(uuid5(NAMESPACE_URL, f'urn:versiona:analysis:{job.public_id}')),
        'queue': 'engine_heavy', 'producer': broker.producer, 'retry': False, 'ignore_result': True,
    }


@pytest.mark.django_db
def test_lost_ack_reuses_the_task_uuid(analysis_job_factory, broker):
    """Lost ack reuses the task uuid."""
    job = analysis_job_factory()
    broker.publish.side_effect = [OperationalError('ack lost'), None]

    tasks._dispatch_pending_analysis(job.pk)
    tasks._dispatch_pending_analysis(job.pk)

    first, second = broker.publish.call_args_list
    assert first.kwargs['task_id'] == second.kwargs['task_id']
    job.refresh_from_db()
    assert job.celery_task_id == second.kwargs['task_id']


@pytest.mark.django_db
@pytest.mark.parametrize('state', ['running', 'failed', 'done'])
def test_recovery_ignores_nonpending_jobs(analysis_job_factory, broker, state):
    """Recovery ignores nonpending jobs."""
    job = analysis_job_factory(status=state)

    assert tasks.recover_pending_analysis() == 0
    broker.publish.assert_not_called()
    job.refresh_from_db()
    assert job.status == state


@pytest.mark.django_db
def test_recovery_leaves_a_recently_acknowledged_job(analysis_job_factory, broker):
    """Recovery leaves a recently acknowledged job."""
    analysis_job_factory(celery_task_id='acknowledged-task')

    assert tasks.recover_pending_analysis() == 0
    broker.publish.assert_not_called()


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_recovery_waits_for_minimum_age(analysis_job_factory, broker):
    """Recovery waits for minimum age."""
    job = analysis_job_factory()
    EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now())

    assert tasks.recover_pending_analysis() == 0
    broker.publish.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('trashed_object', ['version', 'document', 'project'])
def test_recovery_ignores_trashed_input(analysis_job_factory, broker, trashed_object):
    """Recovery ignores trashed input."""
    job = analysis_job_factory()
    targets = {
        'version': job.document_version, 'document': job.document_version.document,
        'project': job.document_version.document.project,
    }
    targets[trashed_object].soft_delete()

    assert tasks.recover_pending_analysis() == 0
    assert tasks._dispatch_pending_analysis(job.pk) == 'skipped'
    broker.publish.assert_not_called()


@pytest.mark.django_db
def test_recovery_ignores_an_already_processed_version(analysis_job_factory, broker):
    """Recovery ignores an already processed version."""
    job = analysis_job_factory()
    DocumentVersion.objects.filter(pk=job.document_version_id).update(analysis_status='processing')

    assert tasks.recover_pending_analysis() == 0
    broker.publish.assert_not_called()


@pytest.mark.django_db
def test_recovery_publishes_at_most_twenty_jobs(analysis_job_factory, broker):
    """Recovery publishes at most twenty jobs."""
    jobs = [analysis_job_factory() for _ in range(21)]

    assert tasks.recover_pending_analysis() == 20
    assert EngineJob.objects.filter(celery_task_id='').get().pk == jobs[-1].pk
    assert broker.publish.call_count == 20


@pytest.mark.django_db
def test_recovery_stops_after_broker_failure(analysis_job_factory, broker):
    """Recovery stops after broker failure."""
    analysis_job_factory()
    analysis_job_factory()
    broker.publish.side_effect = OperationalError('unavailable')

    assert tasks.recover_pending_analysis() == 0
    assert broker.publish.call_count == 1


@pytest.mark.django_db
def test_recovery_stops_at_the_round_budget(analysis_job_factory, broker, monkeypatch):
    """Recovery stops at the round budget."""
    analysis_job_factory()
    analysis_job_factory()
    clock = MagicMock(side_effect=[0, 0, 30])
    monkeypatch.setattr(tasks, 'monotonic', clock)

    assert tasks.recover_pending_analysis() == 1
    assert broker.publish.call_count == 1
    clock.assert_called()


@pytest.mark.django_db
def test_nonbroker_errors_are_not_suppressed(analysis_job_factory, broker):
    """Nonbroker errors are not suppressed."""
    job = analysis_job_factory()
    broker.publish.side_effect = ValueError('bad task arguments')

    with pytest.raises(ValueError, match='bad task arguments'):
        tasks._dispatch_pending_analysis(job.pk)


@pytest.mark.django_db(transaction=True)
def test_concurrent_publishers_confirm_one_dispatch(analysis_job_factory, broker):
    """Concurrent publishers confirm one dispatch."""
    job = analysis_job_factory()
    entered = Event()
    release = Event()

    def publish(**kwargs):
        entered.set()
        assert release.wait(5)

    def dispatch():
        close_old_connections()
        try:
            return tasks._dispatch_pending_analysis(job.pk, skip_locked=True)
        finally:
            close_old_connections()

    broker.publish.side_effect = publish
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(dispatch)
        assert entered.wait(5)
        second = pool.submit(dispatch)
        try:
            assert second.result(timeout=5) == 'skipped'
        finally:
            release.set()
        assert first.result(timeout=5) == 'published'
    assert broker.publish.call_count == 1


@pytest.mark.django_db
def test_enqueue_waits_for_outer_commit(analysis_job_factory, broker, django_capture_on_commit_callbacks):
    """Enqueue waits for outer commit."""
    job = analysis_job_factory()

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            returned = tasks.enqueue_analysis(job.document_version)
            broker.publish.assert_not_called()

    assert returned.pk == job.pk
    assert broker.publish.call_count == 1


@pytest.mark.django_db
def test_rolled_back_enqueue_has_no_phantom_dispatch(analysis_job_factory, broker):
    """Rolled back enqueue has no phantom dispatch."""
    job = analysis_job_factory()
    EngineJob.objects.filter(pk=job.pk).delete()

    with pytest.raises(ValueError, match='cancelled'):
        _enqueue_then_rollback(job.document_version)

    broker.publish.assert_not_called()
    assert not EngineJob.objects.exists()


def _enqueue_then_rollback(version):
    with transaction.atomic():
        tasks.enqueue_analysis(version)
        raise ValueError('cancelled')


# ── Stalled deliveries: started or acknowledged work that stopped progressing ──


def _stalled_job(analysis_job_factory, **overrides):
    """A delivery whose last checkpoint is older than the recovery threshold."""
    job = analysis_job_factory(**overrides)
    EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - STALLED_FOR)
    job.refresh_from_db()
    return job


def _stable_task_id(job):
    return str(uuid5(NAMESPACE_URL, f'urn:versiona:analysis:{job.public_id}'))


def _analysis_checkpoint(version):
    """A valid private checkpoint for a version whose analysis is persisted."""
    return {
        'schema': 1,
        'last_completed': 'analysis',
        'analysis_result': {
            'scenario': version.source_scenario,
            'degraded': False,
            'page_count': version.page_count,
            'sections': {'same': 0, 'renamed': 0, 'added': 0, 'removed': 0, 'total': 0},
        },
        'comparison_pk': None,
        'comparison_result': None,
    }


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_recovery_republishes_a_stalled_running_job(analysis_job_factory, broker):
    """Catches: a delivery lost after it started leaving its version processing forever."""
    job = _stalled_job(
        analysis_job_factory, status='running', attempts=1, celery_task_id='lost-delivery',
    )

    published = tasks.recover_pending_analysis()

    assert published == 1
    assert broker.publish.call_args.kwargs['task_id'] == _stable_task_id(job)


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_recovery_republishes_a_stalled_acknowledged_job(analysis_job_factory, broker):
    """Catches: an acknowledged message lost before any worker started it."""
    job = _stalled_job(analysis_job_factory, celery_task_id='lost-message')

    published = tasks.recover_pending_analysis()

    assert published == 1
    assert broker.publish.call_args.kwargs['task_id'] == _stable_task_id(job)


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_recovery_leaves_a_job_without_progress_for_fifteen_minutes(analysis_job_factory, broker):
    """Catches: a threshold below the plan's analysis ceiling duplicating live work."""
    job = analysis_job_factory(status='running', attempts=1, celery_task_id='live-delivery')
    EngineJob.objects.filter(pk=job.pk).update(updated_at=timezone.now() - timedelta(minutes=15))

    assert tasks.recover_pending_analysis() == 0
    broker.publish.assert_not_called()


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_recovery_fails_a_stalled_job_at_the_delivery_cap(analysis_job_factory, broker):
    """Catches: a poison delivery republished forever instead of reaching a final state."""
    job = _stalled_job(
        analysis_job_factory, status='running',
        attempts=tasks.MAX_ANALYSIS_DELIVERIES, celery_task_id='lost-delivery',
    )

    tasks.recover_pending_analysis()

    job.refresh_from_db()
    broker.publish.assert_not_called()
    assert (job.status, job.error_detail) == ('failed', STALLED_ERROR)


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_stalled_failure_marks_an_unanalyzed_version_failed(analysis_job_factory, broker):
    """Catches: a version left processing after its job reached the delivery cap."""
    job = _stalled_job(
        analysis_job_factory, status='running', attempts=tasks.MAX_ANALYSIS_DELIVERIES,
    )
    DocumentVersion.objects.filter(pk=job.document_version_id).update(analysis_status='processing')

    tasks.recover_pending_analysis()

    version = DocumentVersion.objects.get(pk=job.document_version_id)
    assert (version.analysis_status, version.error_detail) == ('failed', STALLED_ERROR)


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_stalled_failure_keeps_an_analyzed_version_ready(analysis_job_factory, broker):
    """Catches: discarding a persisted analysis because only a later phase stalled."""
    job = _stalled_job(
        analysis_job_factory, status='running', attempts=tasks.MAX_ANALYSIS_DELIVERIES,
    )
    version = job.document_version
    DocumentVersion.objects.filter(pk=version.pk).update(analysis_status='ready')
    EngineJob.objects.filter(pk=job.pk).update(
        payload={**job.payload, tasks.PROGRESS_KEY: _analysis_checkpoint(version)},
    )

    tasks.recover_pending_analysis()

    job.refresh_from_db()
    version.refresh_from_db()
    assert (job.status, version.analysis_status) == ('failed', 'ready')


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_stalled_failure_logs_a_sanitized_warning(analysis_job_factory, broker, caplog):
    """Catches: a silent terminal failure, or a warning that leaks the stored object key."""
    job = _stalled_job(
        analysis_job_factory, status='running', attempts=tasks.MAX_ANALYSIS_DELIVERIES,
    )

    tasks.recover_pending_analysis()

    assert f'phase=stalled_recovery action=failed job={job.public_id}' in caplog.text
    assert job.payload['file_key'] not in caplog.text


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
def test_stalled_recovery_keeps_the_job_when_the_broker_fails(analysis_job_factory, broker):
    """Catches: a broker outage consuming the only recovery of a stalled delivery."""
    job = _stalled_job(
        analysis_job_factory, status='running', attempts=1, celery_task_id='lost-delivery',
    )
    broker.publish.side_effect = OperationalError('unavailable')

    tasks.recover_pending_analysis()

    job.refresh_from_db()
    assert broker.publish.call_count == 1
    assert (job.status, job.celery_task_id, job.updated_at) == (
        'running', 'lost-delivery', timezone.now() - STALLED_FOR,
    )


@pytest.mark.django_db
@freeze_time('2026-10-08T12:00:00Z')
@pytest.mark.parametrize('trashed_object', ['version', 'document', 'project'])
def test_recovery_ignores_a_stalled_job_in_the_trash(analysis_job_factory, broker, trashed_object):
    """Catches: resuming analysis for content already sent to the trash."""
    job = _stalled_job(analysis_job_factory, status='running', attempts=1)
    targets = {
        'version': job.document_version, 'document': job.document_version.document,
        'project': job.document_version.document.project,
    }
    targets[trashed_object].soft_delete()

    assert tasks.recover_pending_analysis() == 0
    broker.publish.assert_not_called()


def _deliver(job_id, filename):
    """Run one broker delivery of the analysis task over a deterministic PDF."""
    with patch(
        'engine.tasks.storage_service.get_bytes',
        return_value=(TESTDATA / filename).read_bytes(),
    ):
        return tasks.run_analysis(job_id)


def _analysis_job(version):
    return EngineJob.objects.create(
        job_type=EngineJob.Type.ANALYSIS, document_version=version,
        idempotency_key=f'analysis:v{version.pk}',
        payload={'version_id': version.pk, 'file_key': version.file_key},
    )


@pytest.fixture
def interrupted_delivery(versiona_context, settings, tmp_path):
    """Seal one section of an analyzed v1, then kill the v2 delivery inside a phase."""
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')
    document = Document.objects.create(
        project=versiona_context.project, title='Contrato', slug='contrato-recuperado',
    )

    def pending_version(number):
        version = DocumentVersion.objects.create(
            document=document, number=number, sha256=f'{number:064d}',
            file_key=f'test/recovery/{document.public_id}/v{number}.pdf',
            config_version=versiona_context.config, author=versiona_context.users['editor'],
        )
        document.latest_number = number
        document.save(update_fields=['latest_number'])
        return version

    previous = pending_version(1)
    _deliver(_analysis_job(previous).pk, 'contrato_v1.pdf')
    previous.refresh_from_db()
    seal_service.create_seal(
        previous, versiona_context.users['reviewer'],
        section_keys=['obligaciones-del-contratista'],
    )
    current = pending_version(2)
    job = _analysis_job(current)

    def interrupt(target):
        with patch(target, side_effect=_WorkerKilled), pytest.raises(_WorkerKilled):
            _deliver(job.pk, 'contrato_v2.pdf')
        return current

    return interrupt


def _recover_then_deliver(broker, filename):
    """Run recovery past the threshold, then deliver the message it republished."""
    with freeze_time(timezone.now() + STALLED_FOR):
        tasks.recover_pending_analysis()
    assert broker.publish.call_count == 1, 'Recovery did not republish the stalled delivery'
    _deliver(broker.publish.call_args.kwargs['args'][0], filename)


@pytest.mark.django_db
def test_recovery_resumes_a_delivery_killed_before_d5(interrupted_delivery, broker):
    """Catches: D5 never running, or running twice, after the worker died mid-pipeline."""
    current = interrupted_delivery('reviews.services.seal_service.apply_invalidation')

    _recover_then_deliver(broker, 'contrato_v2.pdf')

    assert SealValidityRecord.objects.filter(to_document_version=current).count() == 1


@pytest.mark.django_db
def test_recovery_keeps_one_invalidation_notice_after_d5_committed(
    interrupted_delivery, broker,
):
    """Catches: a resumed delivery replaying D5 notices that were committed before the crash."""
    interrupted_delivery('observations.services.reanchor_observations')

    _recover_then_deliver(broker, 'contrato_v2.pdf')

    assert Notification.objects.filter(event_key='seal.invalidated').count() == 1
