"""
Trash (soft-delete) services — kit 3 (flows B4/C4, tensions T4/T5/T14).

Hard rules:
- Anything sealed/approved is NEVER trash-eligible (I3; T4: a project with
  seals can only be archived).
- Only the LATEST draft version of a document can go to the trash (T5); its
  number stays reserved forever (I1 tombstones).
- Restore validates collisions (partial uniques, T13) and parent state.
- Physical purge happens after the grace window via the beat task or the
  owner's early-purge endpoint; the PG trigger blocks any other DELETE.
"""

from django.utils.text import slugify

from audit import services as audit
from documents.models import Document, DocumentVersion
from documents.services.version_service import DomainError
from projects.models import Project
from reviews.models import Seal

PURGE_BATCH_SIZE = 100


def _purge_batches(queryset):
    """Bound traversal even on MySQL, whose driver buffers iterator results."""
    last_pk = 0
    while batch := list(
        queryset.filter(pk__gt=last_pk).order_by('pk').only('pk', 'deleted_at')[
            :PURGE_BATCH_SIZE
        ]
    ):
        # delete() clears instance PKs: advance before callers delete the batch.
        last_pk = batch[-1].pk
        yield from batch
        del batch


def _has_protected_versions(versions) -> bool:
    """Historic evidence blocks trash without materializing versions or seals."""
    if versions.filter(is_approved=True).exists():
        return True
    return Seal.objects.filter(document_version_id__in=versions.values('pk')).exists()


def _has_sealed_versions(document: Document) -> bool:
    return _has_protected_versions(DocumentVersion.all_objects.filter(document=document))


def trash_version(version: DocumentVersion, user, request=None):
    if version.is_approved or not version.is_draft:
        raise DomainError('Una versión sellada o aprobada es inmutable: no puede eliminarse.', 409)
    if version.number != version.document.latest_number:
        raise DomainError('Solo la última versión del documento puede eliminarse.', 409)
    version.soft_delete(user)
    audit.record(org=version.document.project.organization,
                 project=version.document.project, actor=user,
                 event_type='version.trashed', obj=version,
                 payload={'number': version.number}, request=request)


def restore_version(version: DocumentVersion, user, request=None):
    if not version.is_trashed:
        raise DomainError('La versión no está en la papelera.', 400)
    if version.document.is_trashed or version.document.project.is_trashed:
        raise DomainError('Restaura primero el documento/proyecto contenedor.', 409)
    newer = DocumentVersion.objects.filter(
        document=version.document, number__gt=version.number
    ).exists()
    if newer:
        raise DomainError(
            'Ya existe una versión posterior: el binario sigue descargable desde la papelera.',
            409,
        )
    version.restore()
    audit.record(org=version.document.project.organization,
                 project=version.document.project, actor=user,
                 event_type='version.restored', obj=version,
                 payload={'number': version.number}, request=request)


def trash_document(document: Document, user, request=None):
    if _has_sealed_versions(document):
        raise DomainError(
            'El documento tiene versiones selladas o aprobadas: archiva el proyecto en su lugar.',
            409,
        )
    document.soft_delete(user)
    audit.record(org=document.project.organization, project=document.project, actor=user,
                 event_type='document.trashed', obj=document,
                 payload={'title': document.title}, request=request)


def restore_document(document: Document, user, request=None):
    if not document.is_trashed:
        raise DomainError('El documento no está en la papelera.', 400)
    if document.project.is_trashed:
        raise DomainError('Restaura primero el proyecto.', 409)
    collision = Document.objects.filter(
        project=document.project, slug=document.slug
    ).exists()
    if collision:
        # Persist the renamed slug while the row is still trashed: restore()
        # flips deleted_at on its own UPDATE, and the alive-only unique index
        # would reject the old slug before the rename ever hit the DB.
        document.slug = f'{slugify(document.slug)[:200]}-restaurado'
        document.save(update_fields=['slug', 'updated_at'])
    document.restore()
    audit.record(org=document.project.organization, project=document.project, actor=user,
                 event_type='document.restored', obj=document,
                 payload={'title': document.title}, request=request)


def trash_project(project: Project, confirm_name: str, user, request=None):
    if (confirm_name or '').strip() != project.name:
        raise DomainError('Escribe el nombre exacto del proyecto para confirmar.', 400)
    if _has_protected_versions(DocumentVersion.all_objects.filter(document__project=project)):
        raise DomainError(
            'El proyecto contiene versiones selladas: solo puede archivarse (T4).', 409
        )
    project.soft_delete(user)
    audit.record(org=project.organization, project=project, actor=user,
                 event_type='project.trashed', obj=project,
                 payload={'name': project.name}, request=request)


def restore_project(project: Project, user, request=None):
    if not project.is_trashed:
        raise DomainError('El proyecto no está en la papelera.', 400)
    if Project.objects.filter(organization=project.organization, slug=project.slug).exists():
        raise DomainError('Hay un proyecto activo con el mismo identificador: renómbralo primero.', 409)
    if project.status == Project.Status.ACTIVE:
        # I13: bringing an active project back adds to the plan's active count.
        from billing.services import check_project_limit

        check_project_limit(project.organization)
    project.restore()
    audit.record(org=project.organization, project=project, actor=user,
                 event_type='project.restored', obj=project,
                 payload={'name': project.name}, request=request)


def archive_project(project: Project, user, request=None):
    project.status = Project.Status.ARCHIVED
    project.save(update_fields=['status', 'updated_at'])
    audit.record(org=project.organization, project=project, actor=user,
                 event_type='project.archived', obj=project, request=request)


def unarchive_project(project: Project, user, request=None):
    if project.status != Project.Status.ACTIVE and not project.is_trashed:
        # I13: reactivation is checked like creation. A trashed project does
        # not count yet; restore_project checks it when it comes back.
        from billing.services import check_project_limit

        check_project_limit(project.organization)
    project.status = Project.Status.ACTIVE
    project.save(update_fields=['status', 'updated_at'])
    audit.record(org=project.organization, project=project, actor=user,
                 event_type='project.unarchived', obj=project, request=request)


def purge_expired(now=None) -> dict:
    """Beat task body: physically delete trashed rows past the grace window.
    Versions first (children), then documents, then projects. Numbers are
    never reused (I1: Document.latest_number is monotonic)."""
    counts = {'versions': 0, 'documents': 0, 'projects': 0}
    for version in _purge_batches(DocumentVersion.all_objects.purgeable(now)):
        version.delete()
        counts['versions'] += 1
    for document in _purge_batches(Document.all_objects.purgeable(now)):
        DocumentVersion.all_objects.filter(document=document).update(
            deleted_at=document.deleted_at
        )
        for version in _purge_batches(DocumentVersion.all_objects.filter(document=document)):
            version.delete()
        document.delete()
        counts['documents'] += 1
    for project in _purge_batches(Project.all_objects.purgeable(now)):
        for document in _purge_batches(Document.all_objects.filter(project=project)):
            for version in _purge_batches(DocumentVersion.all_objects.filter(document=document)):
                version.soft_delete()
                version.delete()
            document.delete()
        project.delete()
        counts['projects'] += 1
    return counts
