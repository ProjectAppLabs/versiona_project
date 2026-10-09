"""D4-C01: seals, withdrawals and uploads of one document serialize on its row.

The threaded tests contend through real MySQL connections (one per thread),
following the pattern of test_seal_plan_concurrency.py.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Event

import pytest
from audit.models import AuditEvent
from django.db import close_old_connections, connections
from documents.models import DocumentVersion
from documents.services import storage_service, version_service
from documents.services.version_service import DomainError
from notifications.models import Notification
from projects.services import config_service

from reviews.models import ReviewRequest, Seal
from reviews.services import review_service, seal_service

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'
# How long the first transaction waits for a contender at the approval count.
# Serialized seals never meet there: the contender waits on the document lock.
MEETING_SECONDS = 5


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


def upload(document, fixture, message, author):
    """Upload a PDF fixture through the complete analyzed-version lifecycle."""
    intent = version_service.create_upload_intent(document, author)
    storage_service.put_bytes(intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf')
    version, _ = version_service.complete_upload(document, intent.upload_id, message, author)
    return version


def _sealable_version(context, required):
    """An analyzed v1 whose pinned policy needs `required` full-coverage seals."""
    config_service.update_config(
        context.project, context.users['admin'], approval_policy={'required': required},
    )
    document = version_service.create_document(
        context.project, f'Sellos simultáneos {required}', context.users['editor'],
    )
    return upload(document, 'contrato_v1.pdf', 'v1', context.users['editor'])


def _is_approval_count(sql):
    """The read that decides approval, not the duplicate-seal probe."""
    return (
        sql.startswith('SELECT')
        and 'FROM `reviews_seal`' in sql
        and 'SELECT 1 AS' not in sql
        and '`reviews_seal`.`reviewer_id` =' not in sql
    )


def _seal_worker(version_id, reviewer, meeting):
    close_old_connections()
    connection = connections['default']
    met = Event()

    def meet_before_counting(execute, sql, params, many, context):
        if _is_approval_count(sql) and not met.is_set():
            met.set()
            try:
                # Unserialized transactions both count here before either
                # commits; a serialized contender never arrives in time.
                meeting.wait()
            except BrokenBarrierError:
                pass
        return execute(sql, params, many, context)

    try:
        version = DocumentVersion.objects.get(pk=version_id)
        with connection.execute_wrapper(meet_before_counting):
            seal_service.create_seal(version, reviewer, covers_all=True)
        return 'sealed'
    except Exception as exc:  # the asserting thread reports any failure
        return type(exc).__name__
    finally:
        connection.close()


def _seal_concurrently(context, version, aliases):
    meeting = Barrier(len(aliases), timeout=MEETING_SECONDS)
    with ThreadPoolExecutor(max_workers=len(aliases)) as executor:
        futures = [
            executor.submit(_seal_worker, version.pk, context.users[alias], meeting)
            for alias in aliases
        ]
        return [future.result(timeout=120) for future in futures]


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('D4-C01')
def test_two_required_concurrent_seals_approve_the_version_once(versiona_context):
    """Catches: both transactions counting one seal each and never approving."""
    version = _sealable_version(versiona_context, required=2)

    outcomes = _seal_concurrently(versiona_context, version, ['reviewer', 'admin'])

    version.refresh_from_db()
    assert outcomes == ['sealed', 'sealed']
    assert version.is_approved is True
    assert AuditEvent.objects.filter(event_type='version.approved').count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('D4-C01')
def test_two_required_concurrent_seals_complete_the_review_request(versiona_context):
    """Catches: each seal seeing the other assignment pending, leaving it open."""
    context = versiona_context
    version = _sealable_version(context, required=2)
    review = review_service.create_review_request(
        version, context.users['editor'], [context.users['reviewer'].pk, context.users['admin'].pk],
    )

    _seal_concurrently(context, version, ['reviewer', 'admin'])

    review.refresh_from_db()
    assert review.status == ReviewRequest.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('D4-C01')
def test_one_required_concurrent_seals_both_persist(versiona_context):
    """Catches: two approvals racing on the version row (deadlock 1213 → 500)."""
    version = _sealable_version(versiona_context, required=1)

    outcomes = _seal_concurrently(versiona_context, version, ['reviewer', 'admin'])

    assert outcomes == ['sealed', 'sealed']
    assert Seal.objects.filter(document_version=version, revoked_at__isnull=True).count() == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('D4-C01')
def test_one_required_concurrent_seals_announce_the_approval_once(versiona_context):
    """Catches: both transactions approving, duplicating the event and the notice."""
    version = _sealable_version(versiona_context, required=1)

    _seal_concurrently(versiona_context, version, ['reviewer', 'admin'])

    assert AuditEvent.objects.filter(event_type='version.approved').count() == 1
    assert Notification.objects.filter(event_key='version.approved').count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('D4-E01')
def test_seal_waiting_behind_an_upload_is_rejected_for_the_superseded_version(versiona_context):
    """Catches: a seal checked before the newer version committed, approving
    the superseded one (I10 needs the document lock, not only a read)."""
    context = versiona_context
    editor = context.users['editor']
    document = version_service.create_document(context.project, 'Subida simultánea', editor)
    v1 = upload(document, 'contrato_v1.pdf', 'v1', editor)
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v2.pdf').read_bytes(), 'application/pdf',
    )
    upload_locked = Event()
    seal_waiting = Event()

    def hold_the_document(execute, sql, params, many, ctx):
        result = execute(sql, params, many, ctx)
        if 'FOR UPDATE' in sql and 'FROM `documents_document`' in sql and not upload_locked.is_set():
            upload_locked.set()
            seal_waiting.wait(MEETING_SECONDS)
        return result

    def reach_the_document(execute, sql, params, many, ctx):
        if 'FOR UPDATE' in sql and 'FROM `documents_document`' in sql:
            seal_waiting.set()
        return execute(sql, params, many, ctx)

    def upload_worker():
        close_old_connections()
        connection = connections['default']
        try:
            with connection.execute_wrapper(hold_the_document):
                version_service.complete_upload(document, intent.upload_id, 'v2', editor)
        finally:
            connection.close()

    def seal_worker():
        close_old_connections()
        connection = connections['default']
        try:
            assert upload_locked.wait(60), 'The upload never locked the document'
            version = DocumentVersion.objects.get(pk=v1.pk)
            with connection.execute_wrapper(reach_the_document):
                seal_service.create_seal(version, context.users['reviewer'], covers_all=True)
            return 'sealed'
        except DomainError as exc:
            return exc.status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        uploading = executor.submit(upload_worker)
        sealing = executor.submit(seal_worker)
        outcome = sealing.result(timeout=120)
        uploading.result(timeout=300)

    assert outcome == 409
    assert not Seal.objects.filter(document_version=v1).exists()


@pytest.mark.django_db
@pytest.mark.escenario('D4-C01')
def test_seal_after_a_concurrent_approval_does_not_announce_it_again(versiona_context):
    """Catches: create_seal trusting the approval flag it loaded before taking
    the document lock (a concurrent seal may have approved the version)."""
    context = versiona_context
    version = _sealable_version(context, required=1)
    stale = DocumentVersion.objects.get(pk=version.pk)
    seal_service.create_seal(version, context.users['admin'], covers_all=True)

    seal_service.create_seal(stale, context.users['reviewer'], covers_all=True)

    assert AuditEvent.objects.filter(event_type='version.approved').count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('D4-A02')
def test_withdrawal_after_a_concurrent_approval_is_rejected(versiona_context):
    """Catches: revoke_seal trusting a stale approval flag (DP-08 forbids
    withdrawing a seal that supports an approved version)."""
    context = versiona_context
    version = _sealable_version(context, required=2)
    first = seal_service.create_seal(version, context.users['reviewer'], covers_all=True)
    stale_seal = Seal.objects.select_related('document_version').get(pk=first.pk)
    seal_service.create_seal(
        DocumentVersion.objects.get(pk=version.pk), context.users['admin'], covers_all=True,
    )

    with pytest.raises(DomainError) as rejection:
        seal_service.revoke_seal(stale_seal, context.users['reviewer'])

    assert rejection.value.status_code == 409
