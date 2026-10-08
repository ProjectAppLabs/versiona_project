"""Durable analysis intentions recover without repeating acknowledged publication."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import NAMESPACE_URL, uuid5

import pytest
from django.db import close_old_connections, transaction
from django.utils import timezone
from documents.models import Document, DocumentVersion
from freezegun import freeze_time
from kombu.exceptions import OperationalError

from engine import tasks
from engine.models import EngineJob


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
def test_recovery_never_republishes_an_acknowledged_job(analysis_job_factory, broker):
    """Recovery never republishes an acknowledged job."""
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
