"""D3 observation services: threads, the I14 state machine and re-anchoring."""

from django.db import transaction

from audit import services as audit
from documents.models import DocumentVersion, SectionVersion
from documents.services.version_service import DomainError, ensure_writable
from notifications.services import notify

from .models import Observation, ObservationAnchor, ObservationReply

# I14: open → answered → resolved, plus reopen (→ open). Nothing else.
VALID_TRANSITIONS = {
    ('open', 'answered'),
    ('answered', 'resolved'),
    ('answered', 'open'),
    ('resolved', 'open'),
}


def _doc_link(document) -> str:
    project = document.project
    return f'/projects/{project.public_id}/documents/{document.public_id}'


@transaction.atomic
def create_observation(
    version: DocumentVersion, author, *, body: str, section_key: str = '',
    page: int = 1, quads=None, snippet: str = '', request=None,
) -> Observation:
    document = version.document
    ensure_writable(document.project)
    if not body.strip():
        raise DomainError('La observación necesita un texto.', 400)

    section = None
    if section_key:
        snap = (
            SectionVersion.objects.filter(
                document_version=version, section__stable_key=section_key
            )
            .select_related('section')
            .first()
        )
        if snap is None:
            raise DomainError(f'La sección "{section_key}" no existe en esta versión.', 400)
        section = snap.section
        if not quads:
            quads = snap.bboxes
            page = snap.page_start

    observation = Observation.objects.create(
        document=document,
        section=section,
        created_on_version=version,
        author=author,
        body=body.strip(),
    )
    ObservationAnchor.objects.create(
        observation=observation,
        document_version=version,
        page=page,
        quads=quads or [],
        text_snippet=snippet[:300],
        method=ObservationAnchor.Method.EXACT,
    )

    project = document.project
    audit.record(
        org=project.organization, project=project, actor=author,
        event_type='observation.created', obj=observation,
        payload={'version': version.number, 'section': section_key or None},
        request=request,
    )
    if version.author and version.author != author:
        notify(
            user=version.author, event_key='observation.created',
            org=project.organization, project=project,
            context={'author': author.email, 'document': document.title,
                     'section': section_key or f'página {page}',
                     'excerpt': body.strip()[:140]},
            link=_doc_link(document),
            payload={'observation': str(observation.public_id)},
        )
    return observation


@transaction.atomic
def reply_to_observation(
    observation: Observation, author, body: str, request=None
) -> ObservationReply:
    ensure_writable(observation.document.project)
    if not body.strip():
        raise DomainError('La respuesta necesita un texto.', 400)
    reply = ObservationReply.objects.create(
        observation=observation, author=author, body=body.strip()
    )
    # A reply from someone OTHER than the thread author moves open → answered:
    # the conversation got its counterpart (I14's first hop).
    if (
        observation.status == Observation.Status.OPEN
        and author.pk != observation.author_id
    ):
        observation.status = Observation.Status.ANSWERED
        observation.save(update_fields=['status', 'updated_at'])
        reply.status_change = 'open→answered'
        reply.save(update_fields=['status_change', 'updated_at'])

    project = observation.document.project
    if author.pk != observation.author_id:
        notify(
            user=observation.author, event_key='observation.replied',
            org=project.organization, project=project,
            context={'author': author.email, 'document': observation.document.title,
                     'excerpt': body.strip()[:140]},
            link=_doc_link(observation.document),
            payload={'observation': str(observation.public_id)},
        )
    return reply


@transaction.atomic
def set_observation_status(
    observation: Observation, actor, new_status: str, *,
    resolved_in_version: DocumentVersion | None = None, request=None,
) -> Observation:
    """I14 state machine. Resolution belongs to the thread author (their doubt,
    their sign-off) or a project admin."""
    ensure_writable(observation.document.project)
    current = observation.status
    if (current, new_status) not in VALID_TRANSITIONS:
        raise DomainError(
            f'Transición inválida: {current} → {new_status} (I14 permite '
            'open→answered→resolved y reabrir).',
            409,
        )
    if new_status == Observation.Status.RESOLVED:
        from core.permissions import resolve_effective_role

        role = resolve_effective_role(actor, observation.document.project)
        if actor.pk != observation.author_id and role != 'admin':
            raise DomainError('Solo quien abrió la observación (o un admin) la resuelve.', 403)

    observation.status = new_status
    if new_status == Observation.Status.RESOLVED:
        observation.resolved_in_version = (
            resolved_in_version
            or observation.document.versions.order_by('-number').first()
        )
    elif new_status == Observation.Status.OPEN:
        observation.resolved_in_version = None
    observation.save(update_fields=['status', 'resolved_in_version', 'updated_at'])

    project = observation.document.project
    audit.record(
        org=project.organization, project=project, actor=actor,
        event_type=f'observation.{new_status}', obj=observation,
        payload={'from': current}, request=request,
    )
    if new_status == Observation.Status.RESOLVED and actor.pk != observation.author_id:
        notify(
            user=observation.author, event_key='observation.resolved',
            org=project.organization, project=project,
            context={'document': observation.document.title,
                     'section': observation.section.stable_key if observation.section else '—',
                     'version': observation.resolved_in_version.number
                     if observation.resolved_in_version else '—'},
            link=_doc_link(observation.document),
            payload={'observation': str(observation.public_id)},
        )
    return observation


@transaction.atomic
def reanchor_observations(version: DocumentVersion) -> dict:
    """One anchor per (observation, version) — I14. Section intact ⇒ exact
    (previous quads carried); content changed ⇒ reanchored to the section's new
    bboxes; section retired ⇒ orphaned. Idempotent (unique constraint)."""
    counters = {'exact': 0, 'reanchored_section': 0, 'orphaned': 0}
    observations = Observation.objects.filter(document=version.document).select_related(
        'section'
    )
    if not observations.exists():
        return counters

    current = {
        snap.section_id: snap
        for snap in SectionVersion.objects.filter(document_version=version)
    }
    previous_number = version.number - 1
    previous_hashes = {
        snap.section_id: snap.body_hash
        for snap in SectionVersion.objects.filter(
            document_version__document=version.document,
            document_version__number=previous_number,
        )
    }

    for observation in observations:
        if ObservationAnchor.objects.filter(
            observation=observation, document_version=version
        ).exists():
            continue  # idempotent re-run
        previous_anchor = (
            observation.anchors.filter(document_version__number__lt=version.number)
            .order_by('-document_version__number')
            .first()
        )
        snap = current.get(observation.section_id) if observation.section_id else None
        if snap is None:
            method = ObservationAnchor.Method.ORPHANED
            page, quads = previous_anchor.page if previous_anchor else 1, []
        elif previous_hashes.get(observation.section_id) == snap.body_hash:
            method = ObservationAnchor.Method.EXACT
            page = previous_anchor.page if previous_anchor else snap.page_start
            quads = previous_anchor.quads if previous_anchor else snap.bboxes
        else:
            method = ObservationAnchor.Method.REANCHORED
            page, quads = snap.page_start, snap.bboxes

        ObservationAnchor.objects.create(
            observation=observation,
            document_version=version,
            page=page,
            quads=quads,
            text_snippet=previous_anchor.text_snippet if previous_anchor else '',
            method=method,
        )
        counters[method] += 1
    return counters
