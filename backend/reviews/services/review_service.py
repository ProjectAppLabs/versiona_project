"""D1 review requests + the D2 assisted-review context."""

from django.db import transaction
from django.utils import timezone

from audit import services as audit
from core.permissions import resolve_effective_role
from documents.models import DocumentVersion, SectionVersion
from documents.services.version_service import DomainError, ensure_writable
from notifications.services import notify

from ..models import ReviewAssignment, ReviewRequest, Seal


@transaction.atomic
def create_review_request(
    version: DocumentVersion, requested_by, reviewer_ids: list, *,
    message: str = '', scope=None, request=None,
) -> ReviewRequest:
    """D1: manual reviewer selection (DP-A7). Opening the request freezes the
    version message (I2b — is_draft consults open requests)."""
    document = version.document
    project = document.project
    ensure_writable(project)
    if version.analysis_status != DocumentVersion.AnalysisStatus.READY:
        raise DomainError('Solo se puede solicitar revisión de una versión analizada.', 409)
    if version.is_trashed:
        raise DomainError('La versión está en la papelera.', 409)
    if ReviewRequest.objects.filter(
        document_version=version, status=ReviewRequest.Status.OPEN
    ).exists():
        raise DomainError('Esta versión ya tiene una revisión abierta.', 409)
    if not reviewer_ids:
        raise DomainError('Elige al menos un revisor.', 400)

    from django.contrib.auth import get_user_model

    User = get_user_model()
    reviewers = list(User.objects.filter(pk__in=reviewer_ids))
    if len(reviewers) != len(set(reviewer_ids)):
        raise DomainError('Revisor no encontrado.', 404)
    reviewer_roles = [(reviewer, resolve_effective_role(reviewer, project)) for reviewer in reviewers]
    # Check the complete selection before exposing any visible candidate's
    # role/self-review error: unavailable IDs must share one privacy response.
    if any(role is None for _, role in reviewer_roles):
        raise DomainError('Revisor no encontrado.', 404)
    for reviewer, role in reviewer_roles:
        if role not in ('reviewer', 'admin'):
            raise DomainError(
                f'{reviewer.email} no puede revisar en este proyecto (rol: {role or "ninguno"}).',
                400,
            )
        if reviewer.pk == requested_by.pk:
            raise DomainError('No puedes asignarte tu propia revisión.', 400)

    review = ReviewRequest.objects.create(
        document_version=version, requested_by=requested_by, message=message
    )
    ReviewAssignment.objects.bulk_create([
        ReviewAssignment(review_request=review, reviewer=reviewer, scope=scope or 'all')
        for reviewer in reviewers
    ])

    audit.record(
        org=project.organization, project=project, actor=requested_by,
        event_type='review.requested', obj=review,
        payload={'version': version.number,
                 'reviewers': [r.email for r in reviewers]},
        request=request,
    )
    for reviewer in reviewers:
        notify(
            user=reviewer, event_key='review.requested',
            org=project.organization, project=project,
            context={
                'document': document.title,
                'version': version.number,
                'requester': requested_by.email,
                'message': message,
            },
            link=(f'/projects/{project.public_id}/documents/{document.public_id}'
                  f'/versions/{version.public_id}'),
            payload={'review': str(review.public_id), 'version': version.number},
        )
    return review


@transaction.atomic
def cancel_review_request(review: ReviewRequest, actor, request=None) -> ReviewRequest:
    if review.status != ReviewRequest.Status.OPEN:
        raise DomainError('La solicitud ya está cerrada.', 409)
    if review.requested_by_id != actor.pk:
        role = resolve_effective_role(actor, review.document_version.document.project)
        if role != 'admin':
            raise DomainError('Solo quien la abrió (o un admin) puede cancelarla.', 403)
    ensure_writable(review.document_version.document.project)
    review.status = ReviewRequest.Status.CANCELLED
    review.closed_at = timezone.now()
    review.save(update_fields=['status', 'closed_at', 'updated_at'])
    project = review.document_version.document.project
    audit.record(
        org=project.organization, project=project, actor=actor,
        event_type='review.cancelled', obj=review,
        payload={'version': review.document_version.number}, request=request,
    )
    return review


def complete_assignment_on_seal(seal: Seal):
    """The seal IS the review act: sealing marks my assignment done, and the
    request completes when every assignment is done."""
    assignments = ReviewAssignment.objects.filter(
        review_request__document_version=seal.document_version,
        review_request__status=ReviewRequest.Status.OPEN,
        reviewer=seal.reviewer,
        status=ReviewAssignment.Status.PENDING,
    ).select_related('review_request')
    for assignment in assignments:
        assignment.status = ReviewAssignment.Status.DONE
        assignment.completed_at = timezone.now()
        assignment.save(update_fields=['status', 'completed_at', 'updated_at'])
        review = assignment.review_request
        if not review.assignments.filter(status=ReviewAssignment.Status.PENDING).exists():
            review.status = ReviewRequest.Status.COMPLETED
            review.closed_at = timezone.now()
            review.save(update_fields=['status', 'closed_at', 'updated_at'])
            project = review.document_version.document.project
            notify(
                user=review.requested_by, event_key='review.completed',
                org=project.organization, project=project,
                context={
                    'document': review.document_version.document.title,
                    'version': review.document_version.number,
                },
                link=(f'/projects/{project.public_id}/documents/'
                      f'{review.document_version.document.public_id}'),
                payload={'review': str(review.public_id)},
            )


def supersede_open_requests(new_version: DocumentVersion):
    """A new upload makes reviewing the old version pointless: open requests on
    OLDER versions of the same document become `superseded`."""
    stale = ReviewRequest.objects.filter(
        document_version__document=new_version.document,
        document_version__number__lt=new_version.number,
        status=ReviewRequest.Status.OPEN,
    )
    for review in stale:
        review.status = ReviewRequest.Status.SUPERSEDED
        review.closed_at = timezone.now()
        review.save(update_fields=['status', 'closed_at', 'updated_at'])


def review_context(version: DocumentVersion, user) -> dict:
    """D2 'already reviewed by you': which sections changed (or not) since the
    LAST version this user sealed — proven by body-hash equality, the same
    currency D5 uses."""
    last_seal = (
        Seal.objects.filter(
            document_version__document=version.document,
            document_version__number__lt=version.number,
            reviewer=user,
            revoked_at__isnull=True,
        )
        .select_related('document_version')
        .order_by('-document_version__number')
        .first()
    )
    if last_seal is None:
        return {'my_last_sealed_version': None, 'changed': [], 'unchanged': []}

    sealed_hashes = {
        snap.section.stable_key: snap.body_hash
        for snap in SectionVersion.objects.filter(
            document_version=last_seal.document_version
        ).select_related('section')
    }
    changed, unchanged = [], []
    current = SectionVersion.objects.filter(document_version=version).select_related('section')
    for snap in current.order_by('order_index'):
        key = snap.section.stable_key
        entry = {'stable_key': key, 'heading': snap.heading_text}
        if sealed_hashes.get(key) == snap.body_hash:
            unchanged.append(entry)
        else:
            changed.append(entry)
    return {
        'my_last_sealed_version': last_seal.document_version.number,
        'changed': changed,
        'unchanged': unchanged,
    }
