"""Section identity persistence: rename re-assignment and thumbnail failure
(docs/plan/05 §4 steps 1–2 — the ground D5 stands on)."""

import pytest

from documents.models import DocumentVersion, Section, SectionLineage, SectionVersion
from engine.services.persistence import persist_analysis


def payload(stable_key: str, heading: str, body_hash: str, order: int = 0) -> dict:
    return {
        'stable_key': stable_key,
        'heading': heading,
        'heading_hash': f'h{body_hash}',
        'body_hash': body_hash,
        'normalized_text': f'texto de {heading}',
        'level': 1,
        'order_index': order,
        'page_start': 1,
        'page_end': 1,
        'bboxes': [{'page': 1, 'x0': 0.1, 'y0': 0.1, 'x1': 0.9, 'y1': 0.2}],
        'char_count': 20,
    }


def analysis(sections: list[dict], thumbnail: bytes = b'\x89PNG\r\n\x1a\nfake') -> dict:
    return {
        'scenario': 'text_native',
        'degraded': False,
        'page_count': 1,
        'sections': sections,
        'thumbnail_png': thumbnail,
    }


@pytest.fixture
def two_versions(document_with_versions, settings):
    settings.DJANGO_ENV = 'test'
    document, versions = document_with_versions(n_versions=2)
    DocumentVersion.all_objects.filter(pk__in=[v.pk for v in versions]).update(
        analysis_status=DocumentVersion.AnalysisStatus.PROCESSING
    )
    return document, [DocumentVersion.objects.get(pk=v.pk) for v in versions]


@pytest.fixture
def three_versions(document_with_versions, settings):
    settings.DJANGO_ENV = 'test'
    document, versions = document_with_versions(n_versions=3)
    DocumentVersion.all_objects.filter(pk__in=[v.pk for v in versions]).update(
        analysis_status=DocumentVersion.AnalysisStatus.PROCESSING
    )
    return document, [DocumentVersion.objects.get(pk=v.pk) for v in versions]


@pytest.mark.django_db
@pytest.mark.escenario('D5-A01')
def test_renamed_section_reuses_the_same_identity_row(two_versions):
    """A section whose heading changed entirely but whose body is byte-identical
    keeps its Section row (step 2 of the matching) — renames never break
    identity, so seals over it survive."""
    document, (v1, v2) = two_versions
    persist_analysis(v1, analysis([payload('clausula-septima', '7. CLAUSULA SEPTIMA', 'aaa')]))
    original = Section.objects.get(document=document, stable_key='clausula-septima')

    persist_analysis(v2, analysis([payload('confidencialidad', '6. CONFIDENCIALIDAD', 'aaa')]))

    reused = Section.objects.get(pk=original.pk)
    assert reused.stable_key == 'confidencialidad'
    assert reused.title_current == '6. CONFIDENCIALIDAD'
    assert Section.objects.filter(document=document).count() == 1
    lineage = SectionLineage.objects.get(document_version=v2)
    assert lineage.relation == SectionLineage.Relation.RENAMED
    assert SectionVersion.objects.filter(section=reused).count() == 2


@pytest.mark.django_db
def test_removed_section_is_retired_with_lineage(two_versions):
    document, (v1, v2) = two_versions
    persist_antes = persist_analysis(
        v1, analysis([payload('uno', '1. UNO', 'aaa'), payload('dos', '2. DOS', 'bbb', 1)])
    )
    assert persist_antes['sections']['total'] == 2

    result = persist_analysis(v2, analysis([payload('uno', '1. UNO', 'aaa')]))

    assert result['sections']['removed'] == 1
    retired = Section.objects.get(document=document, stable_key='dos')
    assert retired.retired_in_version_id == v2.pk
    assert SectionLineage.objects.filter(
        document_version=v2, relation=SectionLineage.Relation.REMOVED
    ).exists()


@pytest.mark.django_db
def test_heading_update_without_key_change_is_not_a_rename(two_versions):
    """Same stable_key + same body but a cosmetic heading tweak: the title is
    refreshed and the relation stays `same` (no lineage row)."""
    document, (v1, v2) = two_versions
    persist_analysis(v1, analysis([payload('uno', '1. UNO', 'aaa')]))

    persist_analysis(v2, analysis([payload('uno', '1.  UNO', 'aaa')]))

    assert SectionLineage.objects.filter(document_version=v2).count() == 0
    assert Section.objects.get(document=document, stable_key='uno').title_current == '1.  UNO'


@pytest.mark.django_db
@pytest.mark.escenario('C1-E04')
def test_thumbnail_failure_does_not_break_the_analysis(two_versions, monkeypatch):
    """A storage hiccup on the thumbnail must not fail the version: the flag
    goes to `failed` and the list falls back to the PDF icon (kit 1)."""
    from documents.services import storage_service

    document, (v1, _) = two_versions

    def boom(*args, **kwargs):
        raise RuntimeError('minio caído')

    monkeypatch.setattr(storage_service, 'put_bytes', boom)

    persist_analysis(v1, analysis([payload('uno', '1. UNO', 'aaa')]))

    v1.refresh_from_db()
    assert v1.thumb_status == DocumentVersion.ThumbStatus.FAILED
    assert v1.analysis_status == DocumentVersion.AnalysisStatus.READY
    assert SectionVersion.objects.filter(document_version=v1).count() == 1


@pytest.mark.django_db
def test_reinstated_heading_reuses_its_retired_identity_row(three_versions):
    """Catches: a heading removed in v2 and restored in v3 colliding with its
    retired row (unique document + stable_key) and failing the analysis."""
    document, (v1, v2, v3) = three_versions
    persist_analysis(
        v1, analysis([payload('uno', '1. UNO', 'aaa'), payload('dos', '2. DOS', 'bbb', 1)])
    )
    original = Section.objects.get(document=document, stable_key='dos')
    persist_analysis(v2, analysis([payload('uno', '1. UNO', 'aaa')]))

    persist_analysis(
        v3, analysis([payload('uno', '1. UNO', 'aaa'), payload('dos', '2. DOS', 'bbb', 1)])
    )

    reinstated = Section.objects.get(document=document, stable_key='dos')
    assert reinstated.pk == original.pk
    assert reinstated.retired_in_version_id is None
    assert SectionVersion.objects.get(
        document_version=v3, section__stable_key='dos'
    ).section_id == original.pk


@pytest.mark.django_db
def test_reinstated_heading_is_recorded_as_an_added_section(three_versions):
    """The reinstatement is new relative to v2: `added` lineage and counter."""
    document, (v1, v2, v3) = three_versions
    persist_analysis(
        v1, analysis([payload('uno', '1. UNO', 'aaa'), payload('dos', '2. DOS', 'bbb', 1)])
    )
    original = Section.objects.get(document=document, stable_key='dos')
    persist_analysis(v2, analysis([payload('uno', '1. UNO', 'aaa')]))

    result = persist_analysis(
        v3, analysis([payload('uno', '1. UNO', 'aaa'), payload('dos', '2. DOS', 'bbb', 1)])
    )

    lineage = SectionLineage.objects.get(document_version=v3)
    assert lineage.relation == SectionLineage.Relation.ADDED
    assert lineage.to_section_id == original.pk
    assert result['sections']['added'] == 1


@pytest.mark.django_db
def test_heading_reused_after_its_body_moved_gets_a_new_identity(two_versions):
    """Catches: the old heading resolving to the row just renamed in the same
    version, which would snapshot one Section twice (IntegrityError)."""
    document, (v1, v2) = two_versions
    persist_analysis(v1, analysis([payload('confidencialidad', 'CONFIDENCIALIDAD', 'aaa')]))
    original = Section.objects.get(document=document, stable_key='confidencialidad')

    persist_analysis(v2, analysis([
        payload('reserva', 'RESERVA', 'aaa'),
        payload('confidencialidad', 'CONFIDENCIALIDAD', 'bbb', 1),
    ]))

    assert Section.objects.get(pk=original.pk).stable_key == 'reserva'
    assert Section.objects.get(
        document=document, stable_key='confidencialidad'
    ).pk != original.pk
