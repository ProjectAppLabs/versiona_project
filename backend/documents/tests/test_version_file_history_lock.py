"""DP-04: the free plan's history lock also covers the in-app viewer URL.

`version_download` already answered 402 for a locked version while
`version_file` signed an inline URL to the very same object.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from documents.models import DocumentVersion


@pytest.fixture
def free_history(versiona_context, document_with_versions):
    """Free org: v1 is past the 30-day window and not the latest; v2 is the latest."""
    org = versiona_context.org
    org.plan = 'free'
    org.save(update_fields=['plan'])
    _, versions = document_with_versions(n_versions=2)
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
        created_at=timezone.now() - timedelta(days=45)
    )
    return versions


def _viewer_url(client, version):
    return client.get(reverse('version-file', kwargs={'ver': version.public_id}))


@pytest.mark.django_db
def test_viewer_url_of_a_locked_version_answers_402_with_upgrade(client_as, free_history):
    """Fails if the inline viewer hands out a version the free plan locks."""
    locked = free_history[0]

    response = _viewer_url(client_as('viewer'), locked)

    assert response.status_code == 402
    assert response.data['upgrade'] is True
    assert 'url' not in response.data


@pytest.mark.django_db
def test_viewer_url_of_the_latest_version_is_served(client_as, free_history):
    """Fails if the lock check blocks the version the free plan keeps open."""
    latest = free_history[1]

    response = _viewer_url(client_as('viewer'), latest)

    assert response.status_code == 200
    assert response.data['url']


@pytest.mark.django_db
def test_viewer_url_on_a_paid_plan_ignores_the_window(client_as, versiona_context, free_history):
    """Fails if the viewer applies the free window whatever the plan."""
    org = versiona_context.org
    org.plan = 'pro'
    org.save(update_fields=['plan'])

    response = _viewer_url(client_as('viewer'), free_history[0])

    assert response.status_code == 200
