"""D3 reanchoring preserves evidence with database work bounded by batches."""

import pytest
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from documents.models import DocumentVersion, Section, SectionVersion

from observations import services
from observations.models import Observation, ObservationAnchor

pytestmark = pytest.mark.django_db

OLD_QUADS = [{'page': 7, 'x0': 0.1, 'y0': 0.2, 'x1': 0.3, 'y1': 0.4}]
NEW_QUADS = [{'page': 3, 'x0': 0.4, 'y0': 0.5, 'x1': 0.6, 'y1': 0.7}]


@pytest.fixture
def reanchor_data(document_with_versions, versiona_context):
    """Build retained evidence without uploads, engine work or notifications."""
    def make(count=1, n_versions=2):
        document, versions = document_with_versions(n_versions=n_versions)
        section = Section.objects.create(
            document=document, stable_key='retained', title_current='Retained',
            created_in_version=versions[0],
        )
        for version in versions:
            SectionVersion.objects.create(
                section=section, document_version=version, heading_text='Retained',
                heading_hash='a' * 64, body_hash='b' * 64,
                normalized_text='retained text ' * 1000, search_text='retained ' * 1000,
                page_start=3, page_end=3, bboxes=NEW_QUADS, order_index=0,
            )
        Observation.objects.bulk_create([
            Observation(
                document=document, section=section, created_on_version=versions[0],
                author=versiona_context.users['reviewer'], body='retained body ' * 1000,
            )
            for _ in range(count)
        ])
        observations = list(Observation.objects.filter(document=document).order_by('pk'))
        ObservationAnchor.objects.bulk_create([
            ObservationAnchor(
                observation=observation, document_version=versions[0], page=7,
                quads=OLD_QUADS, text_snippet='retained snippet', method='exact',
            )
            for observation in observations
        ])
        return document, versions, section, observations

    return make


@pytest.mark.parametrize('count,select_count,insert_count', [(1, 6, 1), (50, 6, 1), (201, 14, 3)])
def test_reanchor_database_work_grows_every_hundred_threads(reanchor_data, count, select_count, insert_count):
    """Catches: per-thread reads or inserts returning to the reanchor pass."""
    _, versions, _, _ = reanchor_data(count)

    with CaptureQueriesContext(connection) as queries:
        counters = services.reanchor_observations(versions[-1])

    statements = [entry['sql'].lstrip().upper() for entry in queries.captured_queries]
    assert sum(sql.startswith('SELECT') for sql in statements) == select_count
    assert sum(sql.startswith('INSERT') for sql in statements) == insert_count
    assert counters == {'exact': count, 'reanchored_section': 0, 'orphaned': 0}
    assert ObservationAnchor.objects.filter(document_version=versions[-1]).count() == count


def test_reanchor_reads_only_bounded_evidence_metadata(reanchor_data):
    """Catches: loading whole bodies, snapshot text or an unlimited thread list."""
    _, versions, _, _ = reanchor_data(201)

    with CaptureQueriesContext(connection) as queries:
        services.reanchor_observations(versions[-1])

    selects = [entry['sql'].lower() for entry in queries.captured_queries
               if entry['sql'].lstrip().upper().startswith('SELECT')]
    thread_pages = [sql for sql in selects if 'prior_anchor_id' in sql]
    assert len(thread_pages) == 4
    assert all('limit 100' in sql for sql in thread_pages)
    assert all('"body"' not in sql and '`body`' not in sql for sql in selects)
    assert all('normalized_text' not in sql and 'search_text' not in sql for sql in selects)


def test_reanchor_leaves_existing_destination_evidence_untouched(reanchor_data):
    """Catches: rewriting retained anchors or counting already completed threads."""
    _, versions, _, observations = reanchor_data(2)
    existing = ObservationAnchor.objects.create(
        observation=observations[0], document_version=versions[-1], page=9,
        quads=OLD_QUADS, text_snippet='already committed', method='orphaned',
    )
    expected = ObservationAnchor.objects.filter(pk=existing.pk).values().get()

    counters = services.reanchor_observations(versions[-1])

    assert ObservationAnchor.objects.filter(pk=existing.pk).values().get() == expected
    assert counters == {'exact': 1, 'reanchored_section': 0, 'orphaned': 0}


@pytest.mark.parametrize('kind,expected', [
    ('exact', ('exact', 3, NEW_QUADS)),
    ('changed', ('reanchored_section', 3, NEW_QUADS)),
    ('missing', ('orphaned', 1, [])),
])
def test_reanchor_without_prior_anchor_uses_snapshot_fallback(reanchor_data, kind, expected):
    """Catches: an absent historical anchor breaking a new thread's fallback."""
    _, versions, section, observations = reanchor_data()
    ObservationAnchor.objects.filter(observation=observations[0]).delete()
    mutations = {
        'exact': lambda: None,
        'changed': lambda: SectionVersion.objects.filter(
            section=section, document_version=versions[-1],
        ).update(body_hash='c' * 64),
        'missing': lambda: SectionVersion.objects.filter(
            section=section, document_version=versions[-1],
        ).delete(),
    }
    mutations[kind]()

    services.reanchor_observations(versions[-1])

    anchor = ObservationAnchor.objects.get(observation=observations[0], document_version=versions[-1])
    assert (anchor.method, anchor.page, anchor.quads) == expected
    assert anchor.text_snippet == ''


def test_reanchor_uses_greatest_prior_version_number(reanchor_data):
    """Catches: choosing insertion order or version-minus-one instead of the last anchor."""
    _, versions, _, observations = reanchor_data(n_versions=4)
    ObservationAnchor.objects.create(
        observation=observations[0], document_version=versions[2], page=11,
        quads=NEW_QUADS, text_snippet='version three', method='exact',
    )
    ObservationAnchor.objects.create(
        observation=observations[0], document_version=versions[1], page=9,
        quads=OLD_QUADS, text_snippet='inserted later', method='exact',
    )

    services.reanchor_observations(versions[-1])

    anchor = ObservationAnchor.objects.get(observation=observations[0], document_version=versions[-1])
    assert (anchor.page, anchor.quads, anchor.text_snippet) == (11, NEW_QUADS, 'version three')


def test_reanchor_keeps_trashed_prior_anchor_evidence(reanchor_data):
    """Catches: a new alive-version filter silently dropping historical coordinates."""
    _, versions, _, observations = reanchor_data()
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(deleted_at=timezone.now())

    services.reanchor_observations(versions[-1])

    anchor = ObservationAnchor.objects.get(observation=observations[0], document_version=versions[-1])
    assert (anchor.method, anchor.page, anchor.quads) == ('exact', 7, OLD_QUADS)


def test_reanchor_keeps_resolved_threads(reanchor_data):
    """Catches: an optimization incorrectly removing resolved threads from I14."""
    _, versions, _, observations = reanchor_data()
    Observation.objects.filter(pk=observations[0].pk).update(status='resolved')

    services.reanchor_observations(versions[-1])

    assert ObservationAnchor.objects.filter(
        observation=observations[0], document_version=versions[-1], method='exact',
    ).count() == 1


def test_reanchor_bulk_insert_populates_timestamps(reanchor_data):
    """Catches: bulk insertion losing the model's timestamp field preparation."""
    _, versions, _, observations = reanchor_data()
    before = timezone.now()

    services.reanchor_observations(versions[-1])

    anchor = ObservationAnchor.objects.get(observation=observations[0], document_version=versions[-1])
    assert before <= anchor.created_at <= timezone.now()
    assert before <= anchor.updated_at <= timezone.now()


def _fail_second_batch(version):
    anchor_writes = 0

    def reject_second_insert(execute, sql, params, many, context):
        nonlocal anchor_writes
        if sql.lstrip().upper().startswith('INSERT') and 'observations_observationanchor' in sql:
            anchor_writes += 1
            if anchor_writes == 2:
                raise IntegrityError('second batch rejected')
        return execute(sql, params, many, context)

    with connection.execute_wrapper(reject_second_insert):
        with pytest.raises(IntegrityError, match='second batch rejected'):
            services.reanchor_observations(version)


def _append_thread_before_anchor_insert(document, version, section, author_id, appended):
    """Inject a real concurrent arrival at the SQL boundary without recursive writes."""
    def append_then_execute(execute, sql, params, many, context):
        if (sql.lstrip().upper().startswith('INSERT')
                and 'observations_observationanchor' in sql and not appended):
            appended.append(Observation.objects.create(
                document=document, section=section, created_on_version=version,
                author_id=author_id, body='arrived later',
            ))
        return execute(sql, params, many, context)

    return append_then_execute


def test_reanchor_second_insert_failure_reverts_the_phase(reanchor_data):
    """Catches: chunking committing part of an analysis phase before its checkpoint."""
    _, versions, _, _ = reanchor_data(201)

    _fail_second_batch(versions[-1])

    assert ObservationAnchor.objects.filter(document_version=versions[-1]).count() == 0


def test_reanchor_failed_phase_retries_without_duplicate_anchors(reanchor_data):
    """Catches: an interrupted pass leaving partial anchors that corrupt its retry."""
    _, versions, _, _ = reanchor_data(201)
    _fail_second_batch(versions[-1])

    counters = services.reanchor_observations(versions[-1])

    assert counters == {'exact': 201, 'reanchored_section': 0, 'orphaned': 0}
    assert ObservationAnchor.objects.filter(document_version=versions[-1]).count() == 201


def test_reanchor_stops_at_its_initial_pk_ceiling(reanchor_data):
    """Catches: a pass consuming threads appended after it captured its input ceiling."""
    document, versions, section, observations = reanchor_data()
    appended = []
    wrapper = _append_thread_before_anchor_insert(
        document, versions[0], section, observations[0].author_id, appended,
    )

    with connection.execute_wrapper(wrapper):
        counters = services.reanchor_observations(versions[-1])

    assert counters == {'exact': 1, 'reanchored_section': 0, 'orphaned': 0}
    assert not ObservationAnchor.objects.filter(
        observation=appended[0], document_version=versions[-1],
    ).exists()


def test_reanchor_without_threads_returns_empty_counts(reanchor_data):
    """Catches: a document without observations failing before any work is needed."""
    _, versions, _, _ = reanchor_data(0)

    counters = services.reanchor_observations(versions[-1])

    assert counters == {'exact': 0, 'reanchored_section': 0, 'orphaned': 0}
