"""B2 complete: content search (Spanish stemming) + status filter on the board.

The content-search tests run with transaction=True on purpose. InnoDB updates a
FULLTEXT index at COMMIT, so rows written inside the usual rollback-only test
transaction are invisible to MATCH ... AGAINST — including to the negative test,
which would otherwise pass no matter how broken the search was.
"""

from pathlib import Path

import pytest

from documents.services import storage_service, version_service

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


@pytest.fixture
def board_with_content(versiona_context):
    editor = versiona_context.users['editor']
    document = version_service.create_document(
        versiona_context.project, 'Contrato indexado', editor
    )
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf'
    )
    version_service.complete_upload(document, intent.upload_id, 'v1', editor)
    return versiona_context


@pytest.fixture
def board_with_trashed_draft(board_with_content):
    """The indexed v1 stays current once its newer draft v2 goes to the trash."""
    from documents.models import Document
    from documents.services import trash_service

    context = board_with_content
    editor = context.users['editor']
    document = Document.objects.get(project=context.project, title='Contrato indexado')
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v2.pdf').read_bytes(), 'application/pdf'
    )
    draft, _ = version_service.complete_upload(document, intent.upload_id, 'borrador', editor)
    trash_service.trash_version(draft, editor)
    return context


def board_url(context, **params):
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    return f'/api/orgs/{context.org.public_id}/projects/?{query}'


@pytest.mark.django_db(transaction=True, reset_sequences=True)
@pytest.mark.escenario('B2-A03')
def test_board_finds_a_project_by_pdf_content(client_as, board_with_content):
    """'anticipo' appears INSIDE the uploaded PDF, not in the project name —
    the board still finds the project."""
    context = board_with_content

    response = client_as('editor').get(board_url(context, q='anticipo'))

    names = [row['name'] for row in response.data['results']]
    assert 'Torre Central' in names


@pytest.mark.django_db(transaction=True, reset_sequences=True)
@pytest.mark.escenario('B2-A03')
def test_content_search_uses_spanish_stemming(client_as, board_with_content):
    """'obligaciones' vs 'obligación': the Spanish stemmer collapses both."""
    context = board_with_content

    response = client_as('editor').get(board_url(context, q='obligación'))

    assert len(response.data['results']) == 1


@pytest.mark.django_db(transaction=True, reset_sequences=True)
@pytest.mark.escenario('B2-A02')
def test_search_misses_return_the_guided_empty_list(client_as, board_with_content):
    context = board_with_content

    response = client_as('editor').get(board_url(context, q='blockchain'))

    assert response.data['results'] == []


@pytest.mark.django_db(transaction=True, reset_sequences=True)
@pytest.mark.escenario('B2-A03')
def test_content_search_ignores_the_text_of_a_trashed_draft(client_as, board_with_trashed_draft):
    """Catches: B2 reading the trashed draft because it holds the highest number.
    'rectificar' stems to a token only the trashed v2 contains."""
    context = board_with_trashed_draft

    response = client_as('editor').get(board_url(context, q='rectificar'))

    assert response.data['results'] == []


@pytest.mark.django_db(transaction=True, reset_sequences=True)
@pytest.mark.escenario('B2-A03')
def test_content_search_finds_the_current_version_after_trashing_a_draft(
    client_as, board_with_trashed_draft,
):
    """Catches: B2 losing the current version's text once a newer draft is trashed."""
    context = board_with_trashed_draft

    response = client_as('editor').get(board_url(context, q='prorroga'))

    assert [row['name'] for row in response.data['results']] == ['Torre Central']


@pytest.mark.django_db
@pytest.mark.escenario('B2-A01')
@pytest.mark.escenario('B2-A04')
def test_status_filter_separates_archived_projects(client_as, versiona_context):
    from documents.services import trash_service

    context = versiona_context
    trash_service.archive_project(context.project, context.users['admin'])

    active = client_as('editor').get(board_url(context, status='active'))
    archived = client_as('editor').get(board_url(context, status='archived'))

    assert active.data['results'] == []
    assert [row['name'] for row in archived.data['results']] == ['Torre Central']
