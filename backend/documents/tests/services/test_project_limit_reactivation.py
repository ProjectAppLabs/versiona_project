"""I13: reactivating a project respects the plan's active-project limit.

Unarchiving or restoring a project is an action that can add an active
project, so it must hit the same `check_project_limit` as creating one.
"""

import pytest
from django.urls import reverse
from projects.models import Project

from documents.services import trash_service
from documents.services.version_service import DomainError


@pytest.fixture
def free_org(versiona_context):
    """The shared context org on the free plan (limit: one active project)."""
    org = versiona_context.org
    org.plan = 'free'
    org.save(update_fields=['plan'])
    return org


@pytest.fixture
def archived_project(versiona_context, free_org):
    project = versiona_context.project
    trash_service.archive_project(project, versiona_context.users['owner'])
    return project


def _occupy_the_only_active_slot(org):
    return Project.objects.create(organization=org, name='Segundo', slug='segundo')


def _status_of(project):
    return Project.all_objects.get(pk=project.pk).status


@pytest.mark.django_db
def test_unarchive_at_the_free_limit_is_rejected(versiona_context, free_org, archived_project):
    """Fails if unarchiving can push a free org past its active-project limit."""
    _occupy_the_only_active_slot(free_org)

    with pytest.raises(DomainError) as exc:
        trash_service.unarchive_project(archived_project, versiona_context.users['owner'])

    assert exc.value.status_code == 402
    assert _status_of(archived_project) == Project.Status.ARCHIVED


@pytest.mark.django_db
def test_unarchive_below_the_free_limit_is_allowed(versiona_context, archived_project):
    """Fails if the limit check blocks a reactivation that fits the plan."""
    trash_service.unarchive_project(archived_project, versiona_context.users['owner'])

    assert _status_of(archived_project) == Project.Status.ACTIVE


@pytest.mark.django_db
def test_unarchive_of_an_active_project_at_the_limit_is_allowed(versiona_context, free_org):
    """Fails if the check counts the project being unarchived against itself."""
    project = versiona_context.project

    trash_service.unarchive_project(project, versiona_context.users['owner'])

    assert _status_of(project) == Project.Status.ACTIVE


@pytest.mark.django_db
def test_restore_of_an_active_project_at_the_free_limit_is_rejected(versiona_context, free_org):
    """Fails if restoring from the trash can exceed the active-project limit."""
    project = versiona_context.project
    project.soft_delete(versiona_context.users['owner'])
    _occupy_the_only_active_slot(free_org)

    with pytest.raises(DomainError) as exc:
        trash_service.restore_project(project, versiona_context.users['owner'])

    assert exc.value.status_code == 402
    assert Project.all_objects.get(pk=project.pk).is_trashed is True


@pytest.mark.django_db
def test_restore_of_an_archived_project_at_the_free_limit_is_allowed(
    versiona_context, free_org, archived_project
):
    """Fails if restoring a project that stays archived is blocked by the limit."""
    archived_project.soft_delete(versiona_context.users['owner'])
    _occupy_the_only_active_slot(free_org)

    trash_service.restore_project(archived_project, versiona_context.users['owner'])

    restored = Project.all_objects.get(pk=archived_project.pk)
    assert restored.is_trashed is False
    assert restored.status == Project.Status.ARCHIVED


@pytest.mark.django_db
def test_unarchiving_inside_the_trash_still_hits_the_limit_on_restore(
    versiona_context, free_org, archived_project
):
    """Fails if unarchiving a trashed project opens a path around the limit."""
    owner = versiona_context.users['owner']
    archived_project.soft_delete(owner)
    trash_service.unarchive_project(archived_project, owner)
    _occupy_the_only_active_slot(free_org)

    with pytest.raises(DomainError) as exc:
        trash_service.restore_project(archived_project, owner)

    assert exc.value.status_code == 402
    assert Project.all_objects.get(pk=archived_project.pk).is_trashed is True


@pytest.mark.django_db
def test_unarchive_endpoint_at_the_free_limit_answers_402(client_as, free_org, archived_project):
    """Fails if the API reactivates a project the plan does not allow."""
    _occupy_the_only_active_slot(free_org)

    response = client_as('owner').post(
        reverse('project-unarchive', kwargs={'proj': archived_project.public_id})
    )

    assert response.status_code == 402
    assert 'Mejora tu plan' in response.data['error']
    assert _status_of(archived_project) == Project.Status.ARCHIVED
