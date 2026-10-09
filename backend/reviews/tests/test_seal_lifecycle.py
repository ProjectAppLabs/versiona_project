"""The D5 lifecycle over real integration fixtures.

The fixtures exercise storage, engine, comparison, resolver and notifications:
comparison + resolver + notifications):

contrato_v1 → reviewer A seals §1–2, reviewer B seals §3 (multas) → editor
uploads contrato_v2 (changes §3 and §5, removes §6, adds one, renumbers 7/8)
⇒ A's seal is PRESERVED with evidence · B's seal is INVALIDATED · ONLY B is
notified (S6). This is the queen scenario at the API level.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from audit.models import AuditEvent
from django.db.models import Value
from django.utils import timezone
from documents.services import storage_service, version_service
from notifications.models import Notification

from reviews.models import Seal, SealValidityRecord
from reviews.services import seal_service

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


def upload(document, fixture, message, author):
    """Create one analyzed version through the real object-storage lifecycle."""
    intent = version_service.create_upload_intent(document, author)
    storage_service.put_bytes(intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf')
    version, _ = version_service.complete_upload(document, intent.upload_id, message, author)
    return version


def _add_validity_records(seal, versions, decisions):
    for version, decision in zip(versions, decisions):
        if decision is not None:
            SealValidityRecord.objects.create(
                seal=seal, to_document_version=version, decision=decision,
            )


def _version_state(name):
    from documents.models import DocumentVersion

    return {
        'ready': {'analysis_status': DocumentVersion.AnalysisStatus.READY},
        'trashed': {'deleted_at': timezone.now()},
        'failed': {'analysis_status': DocumentVersion.AnalysisStatus.FAILED},
        'pending': {'analysis_status': DocumentVersion.AnalysisStatus.PENDING},
        'processing': {'analysis_status': DocumentVersion.AnalysisStatus.PROCESSING},
    }[name]


def _arrange_i11_case(seal, versions, decisions, revoked, intermediate, target):
    from documents.models import DocumentVersion

    _add_validity_records(seal, versions[1:], decisions)
    if revoked:
        Seal.objects.filter(pk=seal.pk).update(revoked_at=timezone.now())
        seal.refresh_from_db()
    DocumentVersion.all_objects.filter(pk=versions[1].pk).update(**_version_state(intermediate))
    DocumentVersion.all_objects.filter(pk=versions[2].pk).update(**_version_state(target))


def _failed_delivery(context, document):
    """A delivery whose analysis failed for good: never compared nor sealable (F5)."""
    from documents.models import DocumentVersion

    document.refresh_from_db()
    number = document.latest_number + 1
    version = DocumentVersion.objects.create(
        document=document, number=number, sha256=f'{number:064d}',
        file_key=f'test/failed/{document.public_id}/v{number}/original.pdf',
        analysis_status=DocumentVersion.AnalysisStatus.FAILED,
        config_version=context.config, author=context.users['editor'],
    )
    document.latest_number = number
    document.save(update_fields=['latest_number'])
    return version


def _target_at_number(versions, target_number):
    return (
        versions[target_number - 1]
        if target_number
        else SimpleNamespace(number=0, document_id=versions[0].document_id)
    )


@pytest.fixture
def sealed_v1(versiona_context):
    """Document with v1 analyzed and two seals: A over §1–2, B over §3."""
    context = versiona_context
    editor = context.users['editor']
    reviewer_a = context.users['reviewer']
    reviewer_b = context.users['admin']  # admin can also seal (effective role)
    document = version_service.create_document(context.project, 'Contrato sellado', editor)
    v1 = upload(document, 'contrato_v1.pdf', 'v1', editor)

    seal_a = seal_service.create_seal(
        v1, reviewer_a,
        section_keys=['objeto-del-contrato', 'definiciones'],
    )
    seal_b = seal_service.create_seal(
        v1, reviewer_b,
        section_keys=['obligaciones-del-contratista'],
    )
    return context, document, v1, seal_a, seal_b


@pytest.mark.django_db
@pytest.mark.escenario('D4-F01')
def test_seal_binds_the_exact_content_hashes(sealed_v1):
    """A seal payload retains the hashes that its signature verifies."""
    _, _, v1, seal_a, _ = sealed_v1

    payload = seal_a.signed_payload
    assert payload['version_sha256'] == v1.sha256
    assert {s['stable_key'] for s in payload['sections']} == {
        'objeto-del-contrato', 'definiciones'
    }
    from reviews.services import signing

    assert signing.verify(payload, seal_a.signature) is True


@pytest.mark.django_db
@pytest.mark.escenario('D5-F01')
def test_new_version_preserves_a_and_invalidates_b_selectively(sealed_v1):
    """One changed section invalidates only the seal that covered it."""
    context, document, v1, seal_a, seal_b = sealed_v1
    editor = context.users['editor']

    upload(document, 'contrato_v2.pdf', 'v2 con cambios', editor)

    record_a = SealValidityRecord.objects.get(seal=seal_a)
    record_b = SealValidityRecord.objects.get(seal=seal_b)
    # A sealed sections that did not change: PRESERVED with hash evidence.
    assert record_a.decision == SealValidityRecord.Decision.PRESERVED
    assert {v['stable_key'] for v in record_a.evidence['verified']} == {
        'objeto-del-contrato', 'definiciones'
    }
    # B sealed §3 (multas 2%→5%): INVALIDATED with the change as evidence.
    assert record_b.decision == SealValidityRecord.Decision.INVALIDATED
    assert record_b.reason_code == 'section_modified'
    changed = {c['stable_key'] for c in record_b.evidence['changed']}
    assert changed == {'obligaciones-del-contratista'}


@pytest.mark.django_db
@pytest.mark.escenario('D5-F05')
def test_only_the_invalidated_reviewer_is_notified(sealed_v1):
    """Only a reviewer whose seal broke receives a re-review notification."""
    context, document, _, seal_a, seal_b = sealed_v1
    editor = context.users['editor']

    upload(document, 'contrato_v2.pdf', 'v2', editor)

    # S6: B (invalidated) gets the re-review notification…
    assert Notification.objects.filter(
        user=seal_b.reviewer, event_key='seal.invalidated'
    ).count() == 1
    # …and A (preserved) hears NOTHING about it.
    assert not Notification.objects.filter(
        user=seal_a.reviewer, event_key__in=['seal.invalidated', 'seal.preserved']
    ).exists()


@pytest.mark.django_db
@pytest.mark.escenario('D5-A05')
def test_invalidation_is_idempotent_per_version_pair(sealed_v1):
    """Replaying invalidation does not duplicate its validity record or notice."""
    context, document, _, seal_a, seal_b = sealed_v1
    editor = context.users['editor']
    upload(document, 'contrato_v2.pdf', 'v2', editor)
    from comparisons.models import Comparison

    comparison = Comparison.objects.get(trigger=Comparison.Trigger.AUTO)

    seal_service.apply_invalidation(comparison)  # re-run (I15)

    assert SealValidityRecord.objects.filter(seal=seal_b).count() == 1
    assert Notification.objects.filter(
        user=seal_b.reviewer, event_key='seal.invalidated'
    ).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('D5-F06')
def test_validity_chain_i11_across_versions(sealed_v1):
    """A preserved chain remains valid while an invalidated chain does not."""
    context, document, v1, seal_a, seal_b = sealed_v1
    editor = context.users['editor']

    v2 = upload(document, 'contrato_v2.pdf', 'v2', editor)

    assert seal_service.seal_is_valid_at(seal_a, v1) is True
    assert seal_service.seal_is_valid_at(seal_a, v2) is True  # preserved chain
    assert seal_service.seal_is_valid_at(seal_b, v1) is True  # valid where signed
    assert seal_service.seal_is_valid_at(seal_b, v2) is False  # chain cut


@pytest.mark.django_db
def test_third_delivery_preserves_the_original_seal(sealed_v1):
    """Catches: D5 forgetting a v1 seal after its preservation at v2."""
    context, document, _, seal_a, _ = sealed_v1
    upload(document, 'contrato_v2.pdf', 'v2', context.users['editor'])

    v3 = upload(document, 'contrato_v3.pdf', 'v3', context.users['editor'])

    record = SealValidityRecord.objects.get(seal=seal_a, to_document_version=v3)
    assert record.decision == SealValidityRecord.Decision.PRESERVED
    assert {entry['stable_key'] for entry in record.evidence['verified']} == {
        'objeto-del-contrato', 'definiciones',
    }
    assert seal_service.seal_is_valid_at(seal_a, v3) is True
    assert Notification.objects.filter(user=seal_a.reviewer, event_key='seal.invalidated').count() == 0


@pytest.mark.django_db
def test_third_delivery_does_not_revive_an_invalidated_seal(sealed_v1):
    """Catches: the inherited-seal query ignoring an earlier broken chain."""
    context, document, _, _, seal_b = sealed_v1
    upload(document, 'contrato_v2.pdf', 'v2', context.users['editor'])

    v3 = upload(document, 'contrato_v3.pdf', 'v3', context.users['editor'])

    assert seal_service.seal_is_valid_at(seal_b, v3) is False
    assert list(seal_b.validity_records.values_list('decision', flat=True)) == ['invalidated']
    assert Notification.objects.filter(user=seal_b.reviewer, event_key='seal.invalidated').count() == 1


@pytest.mark.django_db
def test_reinstated_section_does_not_revive_its_invalidated_seal(versiona_context):
    """Catches: reusing a retired Section row resurrecting the seal that D5
    invalidated when the section was removed (the I11 chain stays cut)."""
    context = versiona_context
    editor = context.users['editor']
    document = version_service.create_document(context.project, 'Plazo restituido', editor)
    v1 = upload(document, 'contrato_v1.pdf', 'v1', editor)
    seal = seal_service.create_seal(
        v1, context.users['reviewer'], section_keys=['plazo-de-ejecucion'],
    )
    upload(document, 'contrato_v2.pdf', 'v2 quita el plazo', editor)

    v3 = upload(document, 'contrato_v1.pdf', 'v3 restituye el plazo', editor)

    assert seal_service.seal_is_valid_at(seal, v3) is False


@pytest.mark.django_db
@pytest.mark.escenario('D5-F06')
def test_seal_preserved_across_a_failed_delivery_stays_valid(sealed_v1):
    """Catches: a FAILED version (never compared, F5) cutting the I11 chain of
    a seal that D5 preserved against the last ready version."""
    context, document, _, seal_a, _ = sealed_v1
    _failed_delivery(context, document)

    v3 = upload(document, 'contrato_v2.pdf', 'v3 tras el fallo', context.users['editor'])

    assert seal_service.seal_is_valid_at(seal_a, v3) is True


@pytest.mark.django_db
@pytest.mark.escenario('D5-F06')
def test_delivery_after_a_failed_one_keeps_tracking_the_preserved_seal(sealed_v1):
    """Catches: D5 dropping, without record or notice, a seal whose chain
    crossed a FAILED version."""
    context, document, _, seal_a, _ = sealed_v1
    _failed_delivery(context, document)
    upload(document, 'contrato_v2.pdf', 'v3 tras el fallo', context.users['editor'])

    v4 = upload(document, 'contrato_v3.pdf', 'v4', context.users['editor'])

    assert list(
        seal_a.validity_records.filter(to_document_version=v4).values_list('decision', flat=True)
    ) == ['preserved']


@pytest.mark.django_db
def test_third_delivery_replay_keeps_one_original_seal_record(sealed_v1):
    """Catches: inherited seals duplicating evidence when D5 is replayed."""
    from comparisons.models import Comparison

    context, document, _, seal_a, _ = sealed_v1
    upload(document, 'contrato_v2.pdf', 'v2', context.users['editor'])
    v3 = upload(document, 'contrato_v3.pdf', 'v3', context.users['editor'])
    comparison = Comparison.objects.get(to_version=v3, trigger=Comparison.Trigger.AUTO)
    record = SealValidityRecord.objects.get(seal=seal_a, to_document_version=v3)
    original = (record.pk, record.decision, record.evidence, record.decided_at)

    seal_service.apply_invalidation(comparison)

    stored = SealValidityRecord.objects.get(seal=seal_a, to_document_version=v3)
    assert (stored.pk, stored.decision, stored.evidence, stored.decided_at) == original


@pytest.mark.django_db
@pytest.mark.parametrize(('prior_decision', 'expected_decisions'), [
    (None, []),
    ('pending_confirmation', ['pending_confirmation']),
    ('invalidated', ['invalidated']),
    ('superseded', ['superseded']),
])
def test_d5_excludes_inherited_seals_without_a_preserved_chain(
    versiona_context, document_with_versions, prior_decision, expected_decisions,
):
    """Catches: selecting historical seals without checking the complete I11 chain."""
    from comparisons.models import Comparison

    document, versions = document_with_versions(n_versions=3)
    seal = Seal.objects.create(
        document_version=versions[0], reviewer=versiona_context.users['reviewer'],
        signed_payload={}, signature='chain-selection', key_id='chain-selection',
    )
    _add_validity_records(seal, versions[1:2], [prior_decision])
    comparison = Comparison.objects.create(
        document=document, from_version=versions[1], to_version=versions[2],
        status=Comparison.Status.DONE,
    )

    resolved = seal_service.apply_invalidation(comparison)

    assert resolved == []
    assert list(seal.validity_records.values_list('decision', flat=True)) == expected_decisions


@pytest.mark.django_db
def test_d5_excludes_a_revoked_inherited_seal(versiona_context, document_with_versions):
    """Catches: extending validity after the reviewer withdrew the original seal."""
    from comparisons.models import Comparison

    document, versions = document_with_versions(n_versions=3)
    seal = Seal.objects.create(
        document_version=versions[0], reviewer=versiona_context.users['reviewer'],
        signed_payload={}, signature='revoked-selection', key_id='revoked-selection',
        revoked_at=timezone.now(),
    )
    _add_validity_records(seal, versions[1:2], ['preserved'])
    comparison = Comparison.objects.create(
        document=document, from_version=versions[1], to_version=versions[2],
        status=Comparison.Status.DONE,
    )

    resolved = seal_service.apply_invalidation(comparison)

    assert resolved == []
    assert list(seal.validity_records.values_list('decision', flat=True)) == ['preserved']


@pytest.mark.django_db
def test_d5_excludes_a_valid_seal_from_another_document(versiona_context, document_with_versions):
    """Catches: reusing I11 without restricting its seals to the compared document."""
    from comparisons.models import Comparison

    document, versions = document_with_versions(n_versions=2, document_slug='comparado')
    _, other_versions = document_with_versions(n_versions=1, document_slug='ajeno')
    seal = Seal.objects.create(
        document_version=other_versions[0], reviewer=versiona_context.users['reviewer'],
        covers_all=True, signed_payload={}, signature='foreign-selection', key_id='foreign-selection',
    )
    comparison = Comparison.objects.create(
        document=document, from_version=versions[0], to_version=versions[1],
        status=Comparison.Status.DONE,
    )

    resolved = seal_service.apply_invalidation(comparison)

    assert resolved == []
    assert list(seal.validity_records.values_list('decision', flat=True)) == []
    assert Seal.objects.get(pk=seal.pk).document_version_id == other_versions[0].pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('case', 'records', 'revoked', 'target_number', 'intermediate', 'target', 'expected'),
    [
        ('own_version', (), False, 1, 'ready', 'ready', True),
        ('preserved_chain', ('preserved', 'preserved'), False, 3, 'ready', 'ready', True),
        ('missing_link', (None, 'preserved'), False, 3, 'ready', 'ready', False),
        ('pending_link', ('pending_confirmation', 'preserved'), False, 3, 'ready', 'ready', False),
        ('invalidated_link', ('invalidated', 'preserved'), False, 3, 'ready', 'ready', False),
        ('superseded_link', ('superseded', 'preserved'), False, 3, 'ready', 'ready', False),
        ('revoked_seal', ('preserved', 'preserved'), True, 3, 'ready', 'ready', False),
        ('target_before_seal', (), False, 0, 'ready', 'ready', False),
        ('trashed_intermediate', (None, 'preserved'), False, 3, 'trashed', 'ready', True),
        ('failed_intermediate', (None, 'preserved'), False, 3, 'failed', 'ready', True),
        ('failed_intermediate_unlinked_target', (None, None), False, 3, 'failed', 'ready', False),
        ('pending_intermediate', (None, 'preserved'), False, 3, 'pending', 'ready', False),
        ('processing_intermediate', (None, 'preserved'), False, 3, 'processing', 'ready', False),
        ('target_failed', ('preserved', None), False, 3, 'ready', 'failed', False),
        ('target_pending', ('preserved', None), False, 3, 'ready', 'pending', False),
        ('target_failed_with_link', ('preserved', 'preserved'), False, 3, 'ready', 'failed', False),
        ('target_pending_with_link', ('preserved', 'preserved'), False, 3, 'ready', 'pending', False),
        ('target_trashed_with_link', ('preserved', 'preserved'), False, 3, 'ready', 'trashed', False),
    ],
)
def test_i11_validity_requires_each_live_preserved_link(
    document_with_versions, versiona_context, case, records, revoked, target_number,
    intermediate, target, expected,
):
    """Catches: I11 accepting a missing or non-preserved live chain link,
    demanding one from a FAILED intermediate that D5 never compares (F5), or
    granting validity ON a version that is not an analyzed live one."""
    document, versions = document_with_versions(n_versions=3, document_slug=f'i11-{case}')
    seal = Seal.objects.create(
        document_version=versions[0], reviewer=versiona_context.users['reviewer'],
        signed_payload={}, signature=f'signature-{case}', key_id=f'key-{case}',
    )
    _arrange_i11_case(seal, versions, records, revoked, intermediate, target)
    target_version = _target_at_number(versions, target_number)

    scalar = seal_service.seal_is_valid_at(seal, target_version)
    bulk = seal_service.valid_seals_at_number(
        Seal.objects.filter(pk=seal.pk), Value(target_version.number),
    ).exists()

    assert scalar is expected
    assert bulk is expected


@pytest.mark.django_db
def test_i11_scalar_validity_rejects_target_from_another_document(
    document_with_versions, versiona_context,
):
    """Catches: a seal becoming valid for a same-number version in another document."""
    _, sealed_versions = document_with_versions(n_versions=1, document_slug='sellado')
    _, other_versions = document_with_versions(n_versions=1, document_slug='ajeno')
    seal = Seal.objects.create(
        document_version=sealed_versions[0], reviewer=versiona_context.users['reviewer'],
        signed_payload={}, signature='cross-document', key_id='cross-document',
    )

    valid = seal_service.seal_is_valid_at(seal, other_versions[0])

    assert valid is False


@pytest.mark.django_db
def test_i11_validity_allows_a_missing_numeric_slot_without_live_version(
    document_with_versions, versiona_context,
):
    """Catches: I11 treating a consumed but absent version number as a broken link."""
    document, versions = document_with_versions(n_versions=1, document_slug='hueco')
    from documents.models import DocumentVersion
    target = DocumentVersion.objects.create(
        document=document, number=3, message='v3', sha256='3' * 64,
        file_key=f'test/docs/{document.public_id}/v3/original.pdf',
        analysis_status=DocumentVersion.AnalysisStatus.READY,
        config_version=versiona_context.config, author=versiona_context.users['editor'],
    )
    seal = Seal.objects.create(
        document_version=versions[0], reviewer=versiona_context.users['reviewer'],
        signed_payload={}, signature='number-gap', key_id='number-gap',
    )
    SealValidityRecord.objects.create(
        seal=seal, to_document_version=target, decision=SealValidityRecord.Decision.PRESERVED,
    )

    valid = seal_service.seal_is_valid_at(seal, target)

    assert valid is True


@pytest.mark.django_db
@pytest.mark.escenario('D4-A01')
@pytest.mark.escenario('D4-A02')
def test_seal_can_be_withdrawn_before_approval_but_not_after(sealed_v1):
    """An unapproved seal can be revoked while approval makes remaining seals immutable."""
    context, document, v1, seal_a, _ = sealed_v1
    from documents.models import DocumentVersion

    seal_service.revoke_seal(seal_a, seal_a.reviewer)
    assert Seal.objects.get(pk=seal_a.pk).revoked_at is not None

    # Approve the version → the remaining seal becomes immutable (I5).
    DocumentVersion.all_objects.filter(pk=v1.pk).update(is_approved=True)
    v1.refresh_from_db()
    remaining = Seal.objects.filter(document_version=v1, revoked_at__isnull=True).first()
    with pytest.raises(version_service.DomainError) as exc:
        seal_service.revoke_seal(remaining, remaining.reviewer)
    assert exc.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.parametrize('project_state', ['archived', 'trashed'])
def test_readonly_project_rejects_seal_withdrawal(sealed_v1, project_state):
    """Catches: a reviewer changing evidence in an archived or trashed project."""
    _, _, _, seal, _ = sealed_v1
    project = seal.document_version.document.project
    project.status = {'archived': 'archived', 'trashed': 'active'}[project_state]
    project.deleted_at = {'archived': None, 'trashed': timezone.now()}[project_state]
    project.save(update_fields=['status', 'deleted_at'])
    audit_count = AuditEvent.objects.count()
    notice_count = Notification.objects.count()

    with pytest.raises(version_service.DomainError) as exc:
        seal_service.revoke_seal(seal, seal.reviewer)

    assert exc.value.status_code == 409
    assert str(exc.value) == 'El proyecto está archivado o en la papelera: es de solo lectura.'
    seal.refresh_from_db()
    assert seal.revoked_at is None
    assert AuditEvent.objects.count() == audit_count
    assert Notification.objects.count() == notice_count


@pytest.mark.django_db
@pytest.mark.parametrize('project_state', ['archived', 'trashed'])
def test_restored_project_allows_seal_withdrawal(sealed_v1, project_state):
    """Catches: readonly rejection permanently disabling the reversible withdrawal."""
    _, _, _, seal, _ = sealed_v1
    project = seal.document_version.document.project
    project.status = {'archived': 'archived', 'trashed': 'active'}[project_state]
    project.deleted_at = {'archived': None, 'trashed': timezone.now()}[project_state]
    project.save(update_fields=['status', 'deleted_at'])
    with pytest.raises(version_service.DomainError) as rejection:
        seal_service.revoke_seal(seal, seal.reviewer)
    project.status = 'active'
    project.deleted_at = None
    project.save(update_fields=['status', 'deleted_at'])

    seal_service.revoke_seal(seal, seal.reviewer)

    assert rejection.value.status_code == 409
    seal.refresh_from_db()
    assert seal.revoked_at is not None
    assert AuditEvent.objects.filter(event_type='seal.revoked', object_id_ref=str(seal.public_id)).count() == 1


@pytest.mark.django_db
@pytest.mark.escenario('D4-F02')
def test_covers_all_seal_approves_the_version_and_freezes_it(versiona_context):
    """A covers-all seal approves the version and freezes its editable draft fields.

    This enforces I10 and I5 under the MVP policy.
    """
    context = versiona_context
    editor = context.users['editor']
    reviewer = context.users['reviewer']
    document = version_service.create_document(context.project, 'Aprobable', editor)
    v1 = upload(document, 'contrato_v1.pdf', 'v1', editor)

    seal_service.create_seal(v1, reviewer, covers_all=True)

    v1.refresh_from_db()
    assert v1.is_approved is True
    assert v1.is_draft is False
    with pytest.raises(version_service.DomainError):
        version_service.edit_message(v1, 'tarde: ya está aprobada', editor)
    # The author was told the version got approved.
    assert Notification.objects.filter(
        user=editor, event_key='version.approved'
    ).exists()


@pytest.mark.django_db
@pytest.mark.escenario('C4-E01')
def test_sealed_version_is_not_trash_eligible(sealed_v1):
    """I3 reinforced: a version with seals can never go to the trash."""
    context, document, v1, _, _ = sealed_v1
    from documents.services import trash_service

    with pytest.raises(version_service.DomainError):
        trash_service.trash_version(v1, context.users['editor'])


@pytest.mark.django_db
@pytest.mark.escenario('D4-E01')
def test_sealing_a_superseded_version_is_rejected(versiona_context, document_with_versions):
    """Catches: approving a version a newer delivery already superseded (I10)."""
    _, versions = document_with_versions(n_versions=2)

    with pytest.raises(version_service.DomainError) as rejection:
        seal_service.create_seal(versions[0], versiona_context.users['reviewer'], covers_all=True)

    assert rejection.value.status_code == 409
    assert not Seal.objects.filter(document_version=versions[0]).exists()


@pytest.mark.django_db
@pytest.mark.escenario('D4-E01')
@pytest.mark.parametrize('newer_status', ['pending', 'processing', 'failed'])
def test_newer_version_in_any_analysis_state_blocks_sealing(
    versiona_context, document_with_versions, newer_status,
):
    """I10 is literal: the current version is the newest alive one, analyzed or not."""
    from documents.models import DocumentVersion

    _, versions = document_with_versions(n_versions=2)
    DocumentVersion.all_objects.filter(pk=versions[1].pk).update(analysis_status=newer_status)

    with pytest.raises(version_service.DomainError) as rejection:
        seal_service.create_seal(versions[0], versiona_context.users['reviewer'], covers_all=True)

    assert rejection.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('C4-F01')
def test_trashing_the_newer_draft_makes_the_previous_version_sealable(
    versiona_context, document_with_versions,
):
    """Catches: I10 reading the allocation counter, which still counts the trashed draft."""
    from documents.services import trash_service

    _, versions = document_with_versions(n_versions=2)
    trash_service.trash_version(versions[1], versiona_context.users['editor'])

    seal = seal_service.create_seal(versions[0], versiona_context.users['reviewer'], covers_all=True)

    assert seal.document_version_id == versions[0].pk


@pytest.mark.django_db
@pytest.mark.escenario('D4-L01')
def test_sealing_an_unanalyzed_version_is_rejected(versiona_context, document_with_versions):
    """I10's other half: only an analyzed (ready) version can be sealed."""
    from documents.models import DocumentVersion

    _, versions = document_with_versions(n_versions=1)
    DocumentVersion.all_objects.filter(pk=versions[0].pk).update(
        analysis_status=DocumentVersion.AnalysisStatus.PROCESSING,
    )
    version = DocumentVersion.objects.get(pk=versions[0].pk)

    with pytest.raises(version_service.DomainError) as rejection:
        seal_service.create_seal(version, versiona_context.users['reviewer'], covers_all=True)

    assert rejection.value.status_code == 409


@pytest.mark.django_db
@pytest.mark.escenario('D5-F02')
def test_pending_coordinator_plan_rejects_a_new_seal(versiona_context, document_with_versions):
    """Catches: sealing, and so approving, a version whose D5 plan still waits for the coordinator."""
    _, versions = document_with_versions(n_versions=2)
    inherited = Seal.objects.create(
        document_version=versions[0], reviewer=versiona_context.users['reviewer'],
        signed_payload={}, signature='pending-plan', key_id='pending-plan',
    )
    SealValidityRecord.objects.create(
        seal=inherited, to_document_version=versions[1],
        decision=SealValidityRecord.Decision.PENDING,
        proposed_decision=SealValidityRecord.Decision.INVALIDATED,
        decided_mode=SealValidityRecord.Mode.COORDINATOR,
    )

    with pytest.raises(version_service.DomainError) as rejection:
        seal_service.create_seal(versions[1], versiona_context.users['admin'], covers_all=True)

    assert rejection.value.status_code == 409
    assert not Seal.objects.filter(document_version=versions[1]).exists()
