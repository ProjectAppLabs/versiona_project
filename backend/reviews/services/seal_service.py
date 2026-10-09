"""Seal domain services (D4) + the D5 application layer.

`apply_invalidation` is the bridge between the pure resolver and the world:
it feeds the resolver with the auto-comparison's SectionDiffs and persists its
decisions as SealValidityRecords, notifying ONLY the affected reviewers (S6).
"""

import uuid

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Value
from django.utils import timezone

from audit import services as audit
from comparisons.models import Comparison
from documents.models import Document, DocumentVersion, SectionVersion
from documents.queries import newer_alive_versions
from documents.services.version_service import DomainError, ensure_writable
from notifications.services import notify

from ..models import Seal, SealSection, SealValidityRecord
from . import signing
from .invalidation import (
    MODE_COORDINATOR,
    SealInput,
    resolve_seal_invalidation,
)


def _section_snapshots(version: DocumentVersion) -> dict:
    """{stable_key: (section_id, body_hash)} for the version's live sections."""
    return {
        snap.section.stable_key: (snap.section_id, snap.body_hash)
        for snap in SectionVersion.objects.filter(document_version=version)
        .select_related('section')
    }


def _lock_document(version: DocumentVersion):
    """Serialize seals, withdrawals and uploads of one document (I10, D4-C01)
    on the row `_create_locked_version` locks to allocate a version number.
    Everything the guards read is re-loaded under the lock — analysis and
    trash state, approval, and the project's read-only state: the caller's
    copy predates the lock and a concurrent change may have committed since."""
    Document.all_objects.select_for_update().only('pk').get(pk=version.document_id)
    version.refresh_from_db(
        fields=['analysis_status', 'deleted_at', 'is_approved', 'approved_at'],
    )
    version.document = Document.all_objects.select_related('project__organization').get(
        pk=version.document_id,
    )


@transaction.atomic
def create_seal(
    version: DocumentVersion, reviewer, *, covers_all: bool = False,
    section_keys: list[str] | None = None, request=None,
) -> Seal:
    """D4: sign the exact content the reviewer approves (I6)."""
    _lock_document(version)
    document = version.document
    ensure_writable(document.project)
    if version.analysis_status != DocumentVersion.AnalysisStatus.READY:
        raise DomainError('Solo se puede sellar una versión ya analizada.', 409)
    if version.is_trashed:
        raise DomainError('La versión está en la papelera.', 409)
    if newer_alive_versions(version.document_id, version.number).exists():
        raise DomainError('Solo se puede sellar la versión vigente del documento.', 409)
    if SealValidityRecord.objects.filter(
        to_document_version=version, decision=SealValidityRecord.Decision.PENDING,
    ).exists():
        # D5-F02: a pending coordinator plan blocks approval and new seals.
        raise DomainError(
            'La versión tiene un plan de invalidación pendiente: '
            'el coordinador debe confirmarlo antes de sellar.',
            409,
        )
    if Seal.objects.filter(
        document_version=version, reviewer=reviewer, revoked_at__isnull=True
    ).exists():
        raise DomainError('Ya tienes un sello activo en esta versión.', 409)

    snapshots = _section_snapshots(version)
    if not covers_all:
        section_keys = section_keys or []
        if not section_keys:
            raise DomainError('Elige al menos una sección o sella el documento completo.', 400)
        missing = [key for key in section_keys if key not in snapshots]
        if missing:
            raise DomainError(f'Secciones inexistentes en esta versión: {", ".join(missing)}.', 400)
        covered = [(key, snapshots[key][1]) for key in section_keys]
    else:
        covered = [(key, body_hash) for key, (_, body_hash) in snapshots.items()]

    seal_public_id = uuid.uuid4()
    payload = signing.canonical_payload(
        seal_public_id=seal_public_id,
        version=version,
        reviewer=reviewer,
        covers_all=covers_all,
        sections=covered,
    )
    seal = Seal.objects.create(
        public_id=seal_public_id,
        document_version=version,
        reviewer=reviewer,
        covers_all=covers_all,
        signed_payload=payload,
        signature=signing.sign(payload),
        key_id=signing.key_id(),
    )
    SealSection.objects.bulk_create([
        SealSection(seal=seal, section_id=snapshots[key][0], body_hash=body_hash)
        for key, body_hash in covered
    ])

    audit.record(
        org=document.project.organization, project=document.project,
        actor=reviewer, event_type='seal.created', obj=seal,
        payload={'version': version.number, 'covers_all': covers_all,
                 'sections': [key for key, _ in covered]},
        request=request,
    )
    _notify_author_seal_placed(seal)
    from .review_service import complete_assignment_on_seal

    complete_assignment_on_seal(seal)
    _refresh_approval(version, request=request)
    return seal


def _notify_author_seal_placed(seal: Seal):
    version = seal.document_version
    author = version.author
    if author is None or author == seal.reviewer:
        return
    project = version.document.project
    notify(
        user=author, event_key='seal.placed', org=project.organization, project=project,
        context={
            'reviewer': seal.reviewer.email,
            'version': version.number,
            'document': version.document.title,
            'coverage': ('todo el documento' if seal.covers_all
                         else f'{seal.covered_sections.count()} sección(es)'),
        },
        link=f'/projects/{project.public_id}/documents/{version.document.public_id}',
        payload={'seal': str(seal.public_id), 'version': version.number},
    )


@transaction.atomic
def revoke_seal(seal: Seal, actor, request=None) -> Seal:
    """DP-08: a reviewer may withdraw their own seal only BEFORE approval.
    Append-only: the row is never deleted; `revoked_at` is outside the
    signature and the act leaves an AuditEvent."""
    version = seal.document_version
    if seal.reviewer != actor:
        raise DomainError('Solo el autor del sello puede retirarlo.', 403)
    _lock_document(version)
    ensure_writable(version.document.project)
    seal.refresh_from_db(fields=['revoked_at'])
    if seal.revoked_at is not None:
        raise DomainError('Este sello ya fue retirado.', 409)
    if version.is_approved:
        raise DomainError(
            'La versión ya está aprobada: los sellos que la sustentan son inmutables (I5).', 409
        )
    seal.revoked_at = timezone.now()
    seal.save(update_fields=['revoked_at', 'updated_at'])
    audit.record(
        org=version.document.project.organization, project=version.document.project,
        actor=actor, event_type='seal.revoked', obj=seal,
        payload={'version': version.number}, request=request,
    )
    return seal


def _owner_based_approved(version: DocumentVersion, owners: dict) -> tuple[bool, int]:
    """'all_assigned' (B3): every OWNED section present in this version must be
    covered by an ACTIVE seal from one of its owners."""
    present_keys = set(
        SectionVersion.objects.filter(document_version=version)
        .values_list('section__stable_key', flat=True)
    )
    owned = {key: ids for key, ids in owners.items() if key in present_keys and ids}
    if not owned:
        return False, 0
    seals = list(
        Seal.objects.filter(document_version=version, revoked_at__isnull=True)
        .prefetch_related('covered_sections__section')
    )
    satisfied = 0
    for key, owner_ids in owned.items():
        for seal in seals:
            if seal.reviewer_id not in owner_ids:
                continue
            if seal.covers_all or any(
                cover.section.stable_key == key for cover in seal.covered_sections.all()
            ):
                satisfied += 1
                break
    return satisfied == len(owned), satisfied


def _refresh_approval(version: DocumentVersion, request=None):
    """I10: approval derives from the PINNED config's approval_policy (I8).
    Integer `required` counts full-coverage seals; 'all_assigned' (B3, It5)
    demands every owned section sealed by one of its owners."""
    config = version.config_version
    policy = config.approval_policy or {}
    required = policy.get('required', 1)

    if required == 'all_assigned' and config.section_owners:
        approved, qualifying = _owner_based_approved(version, config.section_owners)
        required_display = f'all_assigned ({len(config.section_owners)} secciones)'
        if approved and not version.is_approved:
            _mark_approved(version, qualifying, required_display, request)
        return

    if not isinstance(required, int):
        required = 1  # 'all_assigned' without owners falls back to one full seal
    active = Seal.objects.filter(document_version=version, revoked_at__isnull=True)
    total_sections = SectionVersion.objects.filter(document_version=version).count()

    qualifying = 0
    for seal in active.prefetch_related('covered_sections'):
        covered = total_sections if seal.covers_all else seal.covered_sections.count()
        if covered >= total_sections and total_sections > 0:
            qualifying += 1

    if qualifying >= required and not version.is_approved:
        _mark_approved(version, qualifying, required, request)


def _mark_approved(version: DocumentVersion, qualifying, required, request=None):
    DocumentVersion.all_objects.filter(pk=version.pk).update(
        is_approved=True, approved_at=timezone.now()
    )
    version.refresh_from_db()
    project = version.document.project
    audit.record(
        org=project.organization, project=project, actor=None,
        event_type='version.approved', obj=version,
        payload={'version': version.number, 'required': str(required),
                 'qualifying': qualifying},
        request=request,
    )
    if version.author:
        notify(
            user=version.author, event_key='version.approved',
            org=project.organization, project=project,
            context={'version': version.number, 'document': version.document.title,
                     'qualifying': qualifying, 'required': required},
            link=f'/projects/{project.public_id}/documents/{version.document.public_id}',
            payload={'version': version.number},
        )


# ── D5: application over a fresh comparison ────────────────────────────────


def _changes_from_comparison(comparison: Comparison) -> dict:
    """SectionDiffs → the resolver's `changes` mapping, enriched with the body
    hashes on each side (the resolver ONLY trusts hash equality)."""
    hashes_from = {
        snap.section.stable_key: snap.body_hash
        for snap in SectionVersion.objects.filter(
            document_version=comparison.from_version
        ).select_related('section')
    }
    hashes_to = {
        snap.section.stable_key: snap.body_hash
        for snap in SectionVersion.objects.filter(
            document_version=comparison.to_version
        ).select_related('section')
    }
    return {
        diff.stable_key: {
            'change_type': diff.change_type,
            'similarity': diff.similarity,
            'body_hash_from': hashes_from.get(diff.stable_key),
            'body_hash_to': hashes_to.get(diff.stable_key),
        }
        for diff in comparison.diffs.all()
    }


@transaction.atomic
def apply_invalidation(
    comparison: Comparison, *, analysis_degraded: bool = False,
) -> list[SealValidityRecord]:
    """Runs D5 for every seal valid at `from_version` per I11, including seals
    inherited from earlier versions. Idempotent per (seal, to_version) — I15.

    The engine supplies verified degradation evidence from either analysis;
    older callers retain the source-scenario safety override.
    """
    from_version = comparison.from_version
    to_version = comparison.to_version
    document = comparison.document
    project = document.project

    seal_rows = list(
        valid_seals_at_number(
            Seal.objects.filter(document_version__document=document),
            Value(from_version.number),
        )
        .prefetch_related('covered_sections__section')
        .select_related('reviewer')
    )
    if not seal_rows:
        return []

    # The NEW version's pinned config governs (I8 — never retroactive).
    mode = to_version.config_version.d5_mode
    # Degraded analysis forces a human decision (DP-03/DP-09).
    if (
        analysis_degraded
        or from_version.source_scenario != 'text_native'
        or to_version.source_scenario != 'text_native'
    ):
        mode = MODE_COORDINATOR

    inputs = [
        SealInput(
            seal_id=str(seal.public_id),
            reviewer_id=str(seal.reviewer_id),
            covers_all=seal.covers_all,
            covered={
                cover.section.stable_key: cover.body_hash
                for cover in seal.covered_sections.all()
            },
        )
        for seal in seal_rows
    ]
    decisions = resolve_seal_invalidation(inputs, _changes_from_comparison(comparison), mode)
    by_id = {str(seal.public_id): seal for seal in seal_rows}

    records = []
    for decision in decisions:
        seal = by_id[decision.seal_id]
        record, created = SealValidityRecord.objects.get_or_create(
            seal=seal,
            to_document_version=to_version,
            defaults={
                'comparison': comparison,
                'decision': decision.decision,
                'proposed_decision': decision.proposed,
                'reason_code': decision.reason_code,
                'evidence': decision.evidence,
                'decided_mode': mode,
                'decided_at': None if decision.decision == 'pending_confirmation'
                else timezone.now(),
            },
        )
        records.append(record)
        if not created:
            continue  # idempotent re-run: never rewrite a decision (I4)

        audit.record(
            org=project.organization, project=project, actor=None,
            event_type=f'seal.{record.decision}', obj=seal,
            payload={'from': from_version.number, 'to': to_version.number,
                     'reason': record.reason_code, 'mode': mode},
        )
        if record.decision == SealValidityRecord.Decision.INVALIDATED:
            # S6: ONLY invalidated reviewers hear about it.
            changed = [c['stable_key'] for c in record.evidence.get('changed', [])]
            notify(
                user=seal.reviewer, event_key='seal.invalidated',
                org=project.organization, project=project,
                context={'document': document.title, 'version': to_version.number,
                         'sections': ', '.join(changed) or 'el documento'},
                link=f'/projects/{project.public_id}/documents/{document.public_id}/'
                     f'compare/{from_version.public_id}/{to_version.public_id}',
                payload={'seal': str(seal.public_id), 'sections': changed,
                         'to_version': to_version.number},
            )

    if any(r.decision == SealValidityRecord.Decision.PENDING for r in records):
        _notify_coordinators_plan_pending(project, document, to_version)

    return records


def _notify_coordinators_plan_pending(project, document, to_version):
    """seal_plan pending: the project admins hold `can_confirm_seal_plan` (DP-07)."""
    from projects.models import ProjectMembership

    admins = ProjectMembership.objects.filter(
        project=project, role=ProjectMembership.Role.ADMIN
    ).select_related('user')
    for membership in admins:
        notify(
            user=membership.user, event_key='seal_plan.pending',
            org=project.organization, project=project,
            context={'document': document.title, 'version': to_version.number},
            link=f'/projects/{project.public_id}/documents/{document.public_id}',
            payload={'version': to_version.number},
        )


@transaction.atomic
def confirm_seal_plan(
    to_version: DocumentVersion, actor, decisions: dict, request=None
) -> list[SealValidityRecord]:
    """Coordinator resolves the pending records. decisions: {seal_public_id:
    'preserved'|'invalidated'}. Confirming `preserved` against hash-different
    evidence is allowed ONLY explicitly — and it stays on the record."""
    project = to_version.document.project
    ensure_writable(project)
    # One version row serializes the complete plan without locking joined
    # reviewers or projects. Read pending records only after this lock: a
    # contender must observe the first coordinator's committed final choices.
    DocumentVersion.all_objects.select_for_update().only('pk').get(pk=to_version.pk)
    pending = list(
        SealValidityRecord.objects.filter(
            to_document_version=to_version,
            decision=SealValidityRecord.Decision.PENDING,
        ).select_related('seal__reviewer', 'seal__document_version').order_by('pk')
    )
    if not pending:
        raise DomainError('No hay plan de invalidación pendiente en esta versión.', 404)

    # Validate the whole submission before any audit or SMTP side effect;
    # rolling back database writes cannot retract a previously sent email.
    for record in pending:
        choice = decisions.get(str(record.seal.public_id))
        if choice not in ('preserved', 'invalidated'):
            raise DomainError(
                f'Falta decisión para el sello {record.seal.public_id}.', 400
            )
    resolved = []
    for record in pending:
        choice = decisions[str(record.seal.public_id)]
        record.decision = choice
        record.decided_mode = SealValidityRecord.Mode.COORDINATOR
        record.decided_by = actor
        record.decided_at = timezone.now()
        record.save(update_fields=['decision', 'decided_mode', 'decided_by',
                                   'decided_at', 'updated_at'])
        resolved.append(record)

        audit.record(
            org=project.organization, project=project, actor=actor,
            event_type=f'seal_plan.confirmed_{choice}', obj=record.seal,
            payload={'to': to_version.number, 'proposed': record.proposed_decision},
            request=request,
        )
        if choice == 'invalidated':
            changed_keys = [c['stable_key'] for c in record.evidence.get('changed', [])]
            notify(
                user=record.seal.reviewer, event_key='seal.invalidated',
                org=project.organization, project=project,
                context={'document': to_version.document.title,
                         'version': to_version.number,
                         'sections': ', '.join(changed_keys) or 'el documento'},
                link=f'/projects/{project.public_id}/documents/{to_version.document.public_id}',
                payload={'seal': str(record.seal.public_id)},
            )
    return resolved


def valid_seals_at_number(queryset, number):
    """I11 as a SQL predicate, for a target-number expression on each seal.

    Validity is only granted ON an analyzed live version: a failed, pending,
    processing or trashed target is never valid, whatever links it carries,
    and the target needs its own preserved link. Up to it, only actual live
    intermediate versions need a preserved link: numbers remain consumed
    after trash/purge (I1), so subtracting version numbers would incorrectly
    invalidate chains with a gap. A FAILED intermediate never participates
    either (F5): D5 compares the next delivery against the last ready one, so
    it never receives a link. Pending or processing intermediates still need
    theirs (F4: an undetermined chain is not valid). A missing, pending,
    invalidated or superseded link fails the same predicate.
    """
    preserved_link = SealValidityRecord.objects.filter(
        seal_id=OuterRef(OuterRef('pk')),
        to_document_version_id=OuterRef('pk'),
        decision=SealValidityRecord.Decision.PRESERVED,
    )
    analyzed_target = DocumentVersion.objects.filter(
        document_id=OuterRef('document_version__document_id'),
        number=OuterRef('_validity_target_number'),
        analysis_status=DocumentVersion.AnalysisStatus.READY,
    )
    missing_link = DocumentVersion.objects.filter(
        document_id=OuterRef('document_version__document_id'),
        number__gt=OuterRef('document_version__number'),
        number__lte=OuterRef('_validity_target_number'),
    ).exclude(
        analysis_status=DocumentVersion.AnalysisStatus.FAILED,
        number__lt=OuterRef('_validity_target_number'),
    ).filter(~Exists(preserved_link))
    return queryset.alias(
        _validity_target_number=number,
        _validity_target_analyzed=Exists(analyzed_target),
        _validity_has_missing_link=Exists(missing_link),
    ).filter(
        revoked_at__isnull=True,
        document_version__number__lte=F('_validity_target_number'),
        _validity_target_analyzed=True,
        _validity_has_missing_link=False,
    )


def seal_is_valid_at(seal: Seal, version: DocumentVersion) -> bool:
    """I11: valid at N iff sealed version ≤ N and every link in the chain up to
    N is `preserved`. The seal's own version counts as valid."""
    if seal.revoked_at is not None:
        return False
    if seal.document_version.document_id != version.document_id:
        return False
    sealed_number = seal.document_version.number
    if version.number < sealed_number:
        return False
    if version.number == sealed_number:
        return True
    return valid_seals_at_number(
        Seal.objects.filter(pk=seal.pk), Value(version.number)
    ).exists()
