"""E4 under real MySQL contention: an issued certificate PDF is never replaced."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connections
from django.utils import timezone

from documents.models import DocumentVersion
from documents.services import storage_service, version_service
from reviews.models import Certificate
from reviews.services import seal_service
from reviews.services.certificate_service import issue_certificate

TESTDATA = Path(__file__).resolve().parents[3] / 'testdata' / 'pdfs'
SERIAL_COUNT = ('COUNT(*)', 'FROM `reviews_certificate`')
ORGANIZATION_LOCK = ('FOR UPDATE', 'FROM `orgs_organization`')


@pytest.fixture(autouse=True)
def _test_env(settings, tmp_path):
    settings.DJANGO_ENV = 'test'
    settings.SEAL_SIGNING_KEY_PATH = str(tmp_path / 'seal_key.pem')


def _approved_version(context, title):
    """One approved version per document, through the real upload and seal flow."""
    editor = context.users['editor']
    document = version_service.create_document(context.project, title, editor)
    intent = version_service.create_upload_intent(document, editor)
    storage_service.put_bytes(
        intent.key, (TESTDATA / 'contrato_v1.pdf').read_bytes(), 'application/pdf'
    )
    version, _ = version_service.complete_upload(document, intent.upload_id, 'v1', editor)
    seal_service.create_seal(version, context.users['reviewer'], covers_all=True)
    return version


def _matches(sql, markers):
    return all(marker in sql for marker in markers)


def _issue_worker(version_id, issuer_id, boundary, committed):
    close_old_connections()
    connection = connections['default']
    try:
        version = DocumentVersion.all_objects.get(pk=version_id)
        issuer = get_user_model().objects.get(pk=issuer_id)
        with connection.execute_wrapper(boundary):
            try:
                certificate = issue_certificate(version, issuer)
            except IntegrityError:
                return 'rejected', None
        return 'issued', certificate.serial
    finally:
        committed.set()
        connection.close()


def _concurrent_issuance(first_version, second_version, issuer):
    """Both issuers compute the next serial before the first one commits.

    Before serialization both COUNTs saw the same committed rows; the second
    issuer then wrote its PDF over the first certificate's committed object.
    """
    first_counted = Event()
    second_reached = Event()
    first_committed = Event()
    second_committed = Event()

    def first_boundary(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if _matches(sql, SERIAL_COUNT):
            first_counted.set()
            assert second_reached.wait(10), 'Second issuance never reached the database'
        return result

    def second_boundary(execute, sql, params, many, context):
        if _matches(sql, ORGANIZATION_LOCK):
            # Serialized issuance waits here for the first commit.
            second_reached.set()
        result = execute(sql, params, many, context)
        if _matches(sql, SERIAL_COUNT):
            second_reached.set()
            assert first_committed.wait(10), 'First issuance did not commit'
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            _issue_worker, first_version.pk, issuer.pk, first_boundary, first_committed,
        )
        assert first_counted.wait(10), 'First issuance never counted the serials'
        second = executor.submit(
            _issue_worker, second_version.pk, issuer.pk, second_boundary, second_committed,
        )
        return first.result(timeout=30), second.result(timeout=30)


@pytest.fixture
def concurrent_issuance(versiona_context):
    alfa = _approved_version(versiona_context, 'Contrato Alfa')
    beta = _approved_version(versiona_context, 'Contrato Beta')
    prefix = f'{versiona_context.org.slug.upper()[:12]}-{timezone.now().year}'
    outcomes = _concurrent_issuance(alfa, beta, versiona_context.users['admin'])
    return prefix, outcomes


def _stored_pdf_matches_snapshot(certificate):
    stored = storage_service.get_bytes(certificate.pdf_key)
    return hashlib.sha256(stored).hexdigest() == certificate.snapshot['pdf_sha256']


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('E4-F03')
def test_concurrent_issuance_keeps_every_issued_pdf_intact(concurrent_issuance):
    """Catches: a contender overwriting the PDF of an already committed certificate."""
    certificates = Certificate.objects.select_related('document_version__document')

    integrity = {
        certificate.document_version.document.title: _stored_pdf_matches_snapshot(certificate)
        for certificate in certificates
    }

    assert integrity == {'Contrato Alfa': True, 'Contrato Beta': True}


@pytest.mark.django_db(transaction=True)
@pytest.mark.escenario('E4-F03')
def test_concurrent_issuance_assigns_consecutive_serials(concurrent_issuance):
    """Catches: two issuers counting the same rows and colliding on one serial."""
    prefix, outcomes = concurrent_issuance

    assert list(outcomes) == [('issued', f'{prefix}-0001'), ('issued', f'{prefix}-0002')]


@pytest.mark.django_db
@pytest.mark.escenario('E4-F03')
def test_colliding_serial_never_replaces_an_issued_pdf(versiona_context):
    """Catches: an object key derived from the serial alone, so any serial
    collision rewrites the PDF of the certificate that already owns it."""
    version = _approved_version(versiona_context, 'Contrato Gamma')
    org = versiona_context.org
    serial = f'{org.slug.upper()[:12]}-{timezone.now().year}-0002'
    legacy_key = f'{storage_service._env_prefix()}/orgs/{org.public_id}/certificates/{serial}.pdf'
    legacy_pdf = b'%PDF-1.4 previously issued certificate'
    storage_service.put_bytes(legacy_key, legacy_pdf, 'application/pdf')
    Certificate.objects.create(
        organization=org, document_version=version, serial=serial,
        issued_by=versiona_context.users['admin'], pdf_key=legacy_key,
        snapshot={'pdf_sha256': hashlib.sha256(legacy_pdf).hexdigest()},
    )

    with pytest.raises(IntegrityError):
        issue_certificate(version, versiona_context.users['admin'])

    assert storage_service.get_bytes(legacy_key) == legacy_pdf
