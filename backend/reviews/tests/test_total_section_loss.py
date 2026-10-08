"""D5-L01: heading identities disappear when a re-delivery uses page fallback.

The page sections still exist. Degradation requires coordinator confirmation
of each invalidation proposal; it never authorizes hash-different preservation.
The separate structural-sealability contract remains an explicit expected failure.
"""

from pathlib import Path

import pytest

from documents.models import DocumentVersion
from documents.services import storage_service, version_service
from engine.services.analysis import analyze_bytes
from engine.services.persistence import persist_analysis
from notifications.models import Notification
from reviews.models import SealValidityRecord
from reviews.services import seal_service

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


def upload(document, fixture, message, author):
    intent = version_service.create_upload_intent(document, author)
    storage_service.put_bytes(intent.key, (TESTDATA / fixture).read_bytes(), 'application/pdf')
    version, _ = version_service.complete_upload(document, intent.upload_id, message, author)
    return version


@pytest.fixture
def total_section_loss(versiona_context):
    """v1 = contrato_v1 with a scoped seal and a covers_all seal; v2 = headless
    prose, which retires every section of v1."""
    context = versiona_context
    editor = context.users['editor']
    document = version_service.create_document(context.project, 'Sin secciones', editor)
    v1 = upload(document, 'contrato_v1.pdf', 'v1', editor)
    scoped = seal_service.create_seal(
        v1, context.users['reviewer'],
        section_keys=['objeto-del-contrato', 'definiciones'],
    )
    whole = seal_service.create_seal(v1, context.users['admin'], covers_all=True)
    v2 = upload(document, 'sin_encabezados.pdf', 'v2 sin encabezados', editor)
    return context, document, v1, v2, scoped, whole


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_the_new_version_keeps_none_of_the_previous_stable_keys(total_section_loss):
    _, document, v1, v2, _, _ = total_section_loss

    keys_v1 = set(
        v1.section_versions.values_list('section__stable_key', flat=True)
    )
    keys_v2 = set(
        v2.section_versions.values_list('section__stable_key', flat=True)
    )
    assert keys_v1.isdisjoint(keys_v2)


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_every_lost_scope_requires_an_invalidation_confirmation(total_section_loss):
    _, _, _, v2, _, _ = total_section_loss

    decisions = set(
        SealValidityRecord.objects.filter(to_document_version=v2)
        .values_list('decision', 'proposed_decision')
    )
    assert decisions == {(SealValidityRecord.Decision.PENDING, SealValidityRecord.Decision.INVALIDATED)}


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_the_scoped_seal_proposal_records_its_removed_sections(total_section_loss):
    _, _, _, v2, scoped, _ = total_section_loss

    record = SealValidityRecord.objects.get(seal=scoped, to_document_version=v2)

    assert record.reason_code == 'section_removed'


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_the_covers_all_seal_proposal_records_the_document_change(total_section_loss):
    _, _, _, v2, _, whole = total_section_loss

    record = SealValidityRecord.objects.get(seal=whole, to_document_version=v2)

    assert record.reason_code == 'document_changed'


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_no_seal_of_the_previous_version_stays_valid_at_the_new_one(total_section_loss):
    _, _, _, v2, scoped, _ = total_section_loss

    assert seal_service.seal_is_valid_at(scoped, v2) is False


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_native_page_fallback_forces_coordinator_confirmation(total_section_loss):
    """Catches: losing degraded=True when source_scenario remains text_native."""
    _, _, _, v2, _, _ = total_section_loss

    assert v2.source_scenario == DocumentVersion.Scenario.TEXT_NATIVE
    assert set(v2.seal_validity_records.values_list('decision', flat=True)) == {'pending_confirmation'}


@pytest.mark.django_db
@pytest.mark.escenario('D5-L01')
def test_the_degraded_plan_records_coordinator_mode(total_section_loss):
    _, _, _, v2, scoped, _ = total_section_loss

    record = SealValidityRecord.objects.get(seal=scoped, to_document_version=v2)

    assert record.decided_mode == SealValidityRecord.Mode.COORDINATOR


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason='Pending product contract: structural loss must reject a new seal')
def test_structural_scope_loss_rejects_a_new_seal(total_section_loss):
    """Known product gap; excluded from required D5-L01 conformance evidence."""
    context, _, _, v2, _, _ = total_section_loss

    with pytest.raises(version_service.DomainError) as exc:
        seal_service.create_seal(v2, context.users['reviewer'], covers_all=True)

    assert exc.value.status_code == 409


@pytest.mark.django_db
def test_pending_scope_loss_does_not_notify_reviewers(total_section_loss):
    """Catches: notifying a reviewer before the degraded proposal is confirmed."""
    _, _, _, version, scoped, whole = total_section_loss

    notices = Notification.objects.filter(
        user__in=[scoped.reviewer, whole.reviewer], event_key='seal.invalidated',
    )

    assert notices.count() == 0
    assert list(version.seal_validity_records.order_by('pk').values_list('decision', flat=True)) == [
        'pending_confirmation', 'pending_confirmation',
    ]


@pytest.mark.django_db
def test_confirmed_scope_loss_invalidates_each_seal(total_section_loss):
    """Catches: coordinator confirmation leaving disappeared seal scopes valid."""
    context, _, _, v2, scoped, whole = total_section_loss
    decisions = {str(seal.public_id): 'invalidated' for seal in [scoped, whole]}

    seal_service.confirm_seal_plan(v2, context.users['admin'], decisions)

    assert set(v2.seal_validity_records.values_list('decision', flat=True)) == {'invalidated'}
    assert Notification.objects.filter(event_key='seal.invalidated').count() == 2


def _unapplied_comparison(context, source_pdf, target_pdf):
    """Prepare real analyses without running the engine's D5 adapter."""
    from comparisons.services import build_comparison

    document = version_service.create_document(context.project, 'Análisis directo', context.users['editor'])

    def persist_pdf(filename, number):
        data = (TESTDATA / filename).read_bytes()
        key = f'test/direct/{document.public_id}/v{number}.pdf'
        storage_service.put_bytes(key, data, 'application/pdf')
        version = DocumentVersion.objects.create(
            document=document, number=number, sha256=storage_service.sha256_of(data),
            file_key=key, size_bytes=len(data), config_version=context.config,
            author=context.users['editor'], analysis_status=DocumentVersion.AnalysisStatus.PENDING,
        )
        result = persist_analysis(version, analyze_bytes(data))
        document.latest_number = number
        document.save(update_fields=['latest_number'])
        return version, result

    source_version, source = persist_pdf(source_pdf, 1)
    seal = seal_service.create_seal(source_version, context.users['reviewer'], covers_all=True)
    target_version, target = persist_pdf(target_pdf, 2)
    comparison = build_comparison(document, source_version, target_version, context.users['editor'])
    return comparison, seal, source['degraded'] or target['degraded']


@pytest.mark.django_db
@pytest.mark.parametrize(('source_pdf', 'target_pdf', 'expected_degraded', 'expected_decision', 'expected_mode'), [
    ('contrato_v1.pdf', 'sin_encabezados.pdf', True, 'pending_confirmation', 'coordinator'),
    ('sin_encabezados.pdf', 'contrato_v1.pdf', True, 'pending_confirmation', 'coordinator'),
    ('contrato_v1.pdf', 'contrato_v2.pdf', False, 'invalidated', 'auto'),
])
def test_d5_uses_verified_degradation_from_either_analysis(
    versiona_context, source_pdf, target_pdf,
    expected_degraded, expected_decision, expected_mode,
):
    """Catches: ignoring native-text degradation from either side of a comparison."""
    comparison, seal, degraded = _unapplied_comparison(
        versiona_context, source_pdf, target_pdf,
    )

    seal_service.apply_invalidation(comparison, analysis_degraded=degraded)

    assert degraded is expected_degraded
    record = SealValidityRecord.objects.get(seal=seal, to_document_version=comparison.to_version)
    assert (record.decision, record.decided_mode) == (expected_decision, expected_mode)
    assert record.proposed_decision == 'invalidated'


@pytest.mark.django_db
def test_degraded_d5_replay_preserves_the_pending_record(versiona_context):
    """Catches: replaying verified degradation finalizing or rewriting its proposal."""
    comparison, seal, degraded = _unapplied_comparison(
        versiona_context, 'contrato_v1.pdf', 'sin_encabezados.pdf',
    )
    seal_service.apply_invalidation(comparison, analysis_degraded=degraded)
    original = SealValidityRecord.objects.get(seal=seal)
    snapshot = (original.pk, original.decision, original.evidence, original.decided_at)

    seal_service.apply_invalidation(comparison, analysis_degraded=degraded)

    stored = SealValidityRecord.objects.get(seal=seal)
    assert (stored.pk, stored.decision, stored.evidence, stored.decided_at) == snapshot
