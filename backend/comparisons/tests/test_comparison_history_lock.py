"""DP-04: comparisons cannot reveal a version the free plan locks.

A comparison carries the word-level diff of both versions, so building,
serving from cache or reading it is access to each of them.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from comparisons.models import Comparison, SectionDiff
from documents.models import DocumentVersion


@pytest.fixture
def free_history(versiona_context, document_with_versions):
    """Free org: v1 is past the 30-day window and not the latest; v2 is the latest."""
    org = versiona_context.org
    org.plan = 'free'
    org.save(update_fields=['plan'])
    document, versions = document_with_versions(n_versions=2)
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
        created_at=timezone.now() - timedelta(days=45)
    )
    return document, versions[0], versions[1]


def _upgrade_to_paid(versiona_context):
    org = versiona_context.org
    org.plan = 'pro'
    org.save(update_fields=['plan'])


def _stored_comparison(document, from_version, to_version):
    comparison = Comparison.objects.create(
        document=document, from_version=from_version, to_version=to_version,
        status=Comparison.Status.DONE,
    )
    SectionDiff.objects.create(
        comparison=comparison, stable_key='alcance',
        change_type=SectionDiff.ChangeType.MODIFIED,
        word_diff=[{'op': 'delete', 'text': 'texto de la versión anterior'}],
    )
    return comparison


def _compare(client, document, from_version, to_version):
    return client.post(
        reverse('document-comparisons', kwargs={'doc': document.public_id}),
        {'from_version': str(from_version.public_id), 'to_version': str(to_version.public_id)},
        format='json',
    )


def _detail(client, comparison):
    return client.get(reverse('comparison-detail', kwargs={'cmp': comparison.public_id}))


def _section_diff(client, comparison):
    return client.get(reverse(
        'comparison-section-diff', kwargs={'cmp': comparison.public_id, 'sec': 'alcance'},
    ))


@pytest.mark.django_db
def test_comparing_a_locked_version_answers_402_without_building(client_as, free_history):
    """Fails if a free org can compute a diff against a locked version."""
    document, locked, latest = free_history

    response = _compare(client_as('viewer'), document, locked, latest)

    assert response.status_code == 402
    assert response.data['upgrade'] is True
    assert Comparison.objects.filter(from_version=locked, to_version=latest).exists() is False


@pytest.mark.django_db
def test_a_cached_comparison_with_a_locked_version_answers_402(client_as, free_history):
    """Fails if the cache serves a diff the lock would refuse to build."""
    document, locked, latest = free_history
    _stored_comparison(document, locked, latest)

    response = _compare(client_as('viewer'), document, locked, latest)

    assert response.status_code == 402
    assert response.data['upgrade'] is True


@pytest.mark.django_db
def test_comparing_on_a_paid_plan_is_built(client_as, versiona_context, free_history):
    """Fails if the comparison check blocks versions the plan allows."""
    document, old, latest = free_history
    _upgrade_to_paid(versiona_context)

    response = _compare(client_as('viewer'), document, old, latest)

    assert response.status_code == 201


@pytest.mark.django_db
def test_detail_of_a_comparison_with_a_locked_version_answers_402(client_as, free_history):
    """Fails if a stored comparison exposes a locked version's changes."""
    document, locked, latest = free_history
    comparison = _stored_comparison(document, locked, latest)

    response = _detail(client_as('viewer'), comparison)

    assert response.status_code == 402
    assert response.data['upgrade'] is True


@pytest.mark.django_db
def test_detail_on_a_paid_plan_is_served(client_as, versiona_context, free_history):
    """Fails if the detail check blocks a comparison the plan allows."""
    document, old, latest = free_history
    comparison = _stored_comparison(document, old, latest)
    _upgrade_to_paid(versiona_context)

    response = _detail(client_as('viewer'), comparison)

    assert response.status_code == 200


@pytest.mark.django_db
def test_section_diff_with_a_locked_version_answers_402(client_as, free_history):
    """Fails if the word-level diff leaks a locked version's text."""
    document, locked, latest = free_history
    comparison = _stored_comparison(document, locked, latest)

    response = _section_diff(client_as('viewer'), comparison)

    assert response.status_code == 402
    assert 'word_diff' not in response.data


@pytest.mark.django_db
def test_section_diff_on_a_paid_plan_is_served(client_as, versiona_context, free_history):
    """Fails if the diff check blocks a comparison the plan allows."""
    document, old, latest = free_history
    comparison = _stored_comparison(document, old, latest)
    _upgrade_to_paid(versiona_context)

    response = _section_diff(client_as('viewer'), comparison)

    assert response.status_code == 200
    assert response.data['word_diff']
