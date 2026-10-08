"""Real MySQL contention at the D5 confirmation transaction boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from audit.models import AuditEvent
from django.db import close_old_connections, connections
from documents.models import DocumentVersion
from documents.services.version_service import DomainError
from notifications.models import Notification

from reviews.models import Seal, SealValidityRecord
from reviews.services import seal_service


def _pending_records(context, versions, seal_count):
    reviewers = [context.users['reviewer'], context.users['editor']]
    records = []
    for reviewer in reviewers[:seal_count]:
        seal = Seal.objects.create(
            document_version=versions[0], reviewer=reviewer,
            signed_payload={}, signature='test-signature', key_id='test-key',
        )
        records.append(SealValidityRecord.objects.create(
            seal=seal, to_document_version=versions[1],
            decision=SealValidityRecord.Decision.PENDING,
            proposed_decision=SealValidityRecord.Decision.INVALIDATED,
            decided_mode=SealValidityRecord.Mode.COORDINATOR,
            evidence={'changed': [{'stable_key': 'alcance', 'change_type': 'modified'}]},
        ))
    return records


def _confirm_worker(version_id, actor, choices, boundary, committed):
    close_old_connections()
    connection = connections['default']
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT CONNECTION_ID()')
            connection_id = cursor.fetchone()[0]
        version = DocumentVersion.all_objects.get(pk=version_id)
        with connection.execute_wrapper(boundary):
            try:
                resolved = seal_service.confirm_seal_plan(version, actor, choices)
            except DomainError as exc:
                return connection_id, exc.status_code, str(exc), []
        snapshots = [(row.pk, row.decision, row.decided_by_id, row.decided_at) for row in resolved]
        return connection_id, 200, '', snapshots
    finally:
        committed.set()
        connection.close()


def _concurrent_confirmation(version, first_actor, second_actor, first_choices, second_choices):
    first_read = Event()
    second_reached = Event()
    first_committed = Event()
    second_committed = Event()

    def first_boundary(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.startswith('SELECT') and 'FROM `reviews_sealvalidityrecord`' in sql:
            first_read.set()
            assert second_reached.wait(10), 'Second confirmation never reached the database'
        return result

    def second_boundary(execute, sql, params, many, context):
        if 'FOR UPDATE' in sql and 'FROM `documents_documentversion`' in sql:
            # After the fix the contender reaches the real row lock before it
            # can read pending records. Let the winner commit to release it.
            second_reached.set()
        result = execute(sql, params, many, context)
        if sql.startswith('SELECT') and 'FROM `reviews_sealvalidityrecord`' in sql:
            # Before the fix both actual SELECTs see pending. MySQL's buffered
            # cursor retains that result while the first transaction commits.
            second_reached.set()
            assert first_committed.wait(10), 'First confirmation did not commit'
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            _confirm_worker, version.pk, first_actor, first_choices,
            first_boundary, first_committed,
        )
        assert first_read.wait(10), 'First confirmation never read the pending plan'
        second = executor.submit(
            _confirm_worker, version.pk, second_actor, second_choices,
            second_boundary, second_committed,
        )
        return first.result(timeout=20), second.result(timeout=20)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('winning_choice', ['preserved', 'invalidated'])
@pytest.mark.parametrize('seal_count', [1, 2])
def test_concurrent_confirmation_keeps_the_first_final_decision(
    versiona_context, document_with_versions, winning_choice, seal_count, record_property,
):
    """Catches: two readers overwriting an I4-final decision with opposite choices."""
    context = versiona_context
    _, versions = document_with_versions(n_versions=2)
    records = _pending_records(context, versions, seal_count)
    opposite = {'preserved': 'invalidated', 'invalidated': 'preserved'}[winning_choice]
    first_choices = {str(row.seal.public_id): winning_choice for row in records}
    second_choices = {str(row.seal.public_id): opposite for row in records}

    first, second = _concurrent_confirmation(
        versions[1], context.users['admin'], context.users['owner'],
        first_choices, second_choices,
    )

    final = list(SealValidityRecord.objects.filter(pk__in=[row.pk for row in records])
                 .order_by('pk').values_list('pk', 'decision', 'decided_by_id', 'decided_at'))
    record_property('mysql_connection_ids', repr((first[0], second[0])))
    record_property('confirmation_statuses', repr((first[1], second[1])))
    record_property('final_decisions', repr([(row[1], row[2]) for row in final]))
    assert first[0] != second[0]
    assert first[1] == 200
    assert final == sorted(first[3])
    assert second[1:3] == (404, 'No hay plan de invalidación pendiente en esta versión.')
    assert AuditEvent.objects.filter(event_type=f'seal_plan.confirmed_{winning_choice}').count() == seal_count
    assert AuditEvent.objects.filter(event_type=f'seal_plan.confirmed_{opposite}').count() == 0
    expected_notices = {'preserved': 0, 'invalidated': seal_count}[winning_choice]
    assert Notification.objects.filter(event_key='seal.invalidated').count() == expected_notices


@pytest.mark.django_db
def test_incomplete_plan_leaves_no_confirmation_effects(
    versiona_context, document_with_versions, mailoutbox,
):
    """Catches: an early decision sending mail before a later missing decision rolls back."""
    context = versiona_context
    _, versions = document_with_versions(n_versions=2)
    records = _pending_records(context, versions, 2)
    choices = {str(records[0].seal.public_id): 'invalidated'}

    with pytest.raises(DomainError) as exc:
        seal_service.confirm_seal_plan(versions[1], context.users['admin'], choices)

    assert exc.value.status_code == 400
    assert str(exc.value) == f'Falta decisión para el sello {records[1].seal.public_id}.'
    assert list(SealValidityRecord.objects.order_by('pk').values_list(
        'decision', 'decided_by_id', 'decided_at',
    )) == [('pending_confirmation', None, None), ('pending_confirmation', None, None)]
    assert AuditEvent.objects.filter(event_type__startswith='seal_plan.confirmed_').count() == 0
    assert Notification.objects.filter(event_key='seal.invalidated').count() == 0
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_rejected_incomplete_plan_can_be_confirmed_later(versiona_context, document_with_versions):
    """Catches: a rejected partial submission consuming any of the pending records."""
    context = versiona_context
    _, versions = document_with_versions(n_versions=2)
    records = _pending_records(context, versions, 2)
    with pytest.raises(DomainError):
        seal_service.confirm_seal_plan(
            versions[1], context.users['admin'], {str(records[0].seal.public_id): 'invalidated'},
        )
    choices = {str(record.seal.public_id): 'invalidated' for record in records}

    resolved = seal_service.confirm_seal_plan(versions[1], context.users['admin'], choices)

    assert len(resolved) == 2
    assert set(SealValidityRecord.objects.values_list('decision', flat=True)) == {'invalidated'}
    assert AuditEvent.objects.filter(event_type='seal_plan.confirmed_invalidated').count() == 2
    assert Notification.objects.filter(event_key='seal.invalidated').count() == 2
