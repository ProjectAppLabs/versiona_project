"""E4 — issue the exportable certificate (docs/plan/01 E4, T6).

Issuance re-verifies EVERY Ed25519 signature at issue time: a certificate is
never a copy of old claims, it is a fresh proof. The PDF embeds the canonical
payloads, the signatures, the public key and offline instructions — no QR, no
online dependency (T6)."""

import hashlib
import io
import json

from django.db import transaction
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as pdf_canvas

from audit import services as audit
from core.models import uuid7
from documents.models import DocumentVersion
from documents.services import storage_service
from documents.services.version_service import DomainError
from orgs.models import Organization

from ..models import Certificate, Seal
from . import signing
from .seal_service import seal_is_valid_at


def _serial_for(org) -> str:
    year = timezone.now().year
    count = Certificate.objects.filter(
        organization=org, created_at__year=year
    ).count() + 1
    return f'{org.slug.upper()[:12]}-{year}-{count:04d}'


def _gather_seals(version: DocumentVersion) -> list[dict]:
    """Active seals VALID at this version, each re-verified NOW (I6)."""
    rows = []
    seals = Seal.objects.filter(
        document_version__document=version.document,
        document_version__number__lte=version.number,
        revoked_at__isnull=True,
    ).select_related('reviewer', 'document_version').prefetch_related(
        'covered_sections__section'
    )
    for seal in seals:
        if not seal_is_valid_at(seal, version):
            continue
        verified = signing.verify(seal.signed_payload, seal.signature)
        rows.append({
            'seal_id': str(seal.public_id),
            'reviewer': seal.reviewer.email,
            'sealed_version': seal.document_version.number,
            'covers_all': seal.covers_all,
            'covered_sections': seal.covered_keys,
            'signed_at': seal.signed_payload.get('signed_at'),
            'signature_valid_now': verified,
            'payload': seal.signed_payload,
            'signature': seal.signature,
            'key_id': seal.key_id,
        })
    return rows


def _render_pdf(serial: str, version: DocumentVersion, seals: list[dict],
                public_key: str, issued_by) -> bytes:
    document = version.document
    project = document.project
    buffer = io.BytesIO()
    page = pdf_canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 2 * cm

    def line(text: str, size=10, bold=False, gap=0.55):
        nonlocal y, page
        if y < 2.5 * cm:
            page.showPage()
            y = height - 2 * cm
        page.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
        page.drawString(2 * cm, y, text[:110])
        y -= gap * cm

    line('VERSIONA — CONSTANCIA DE VALIDEZ', 16, bold=True, gap=0.9)
    line(f'Serial: {serial}', 11, bold=True)
    line(f'Emitida: {timezone.now().strftime("%Y-%m-%d %H:%M UTC")} · por {issued_by.email}')
    line(f'Organización: {project.organization.name}')
    line(f'Proyecto: {project.name}')
    line(f'Documento: {document.title}')
    line(f'Versión: v{version.number} (aprobada)', bold=True)
    line(f'SHA-256 del binario: {version.sha256}', 8)
    y -= 0.4 * cm

    line(f'SELLOS VIGENTES EN v{version.number}: {len(seals)}', 12, bold=True, gap=0.8)
    for row in seals:
        line(f'• {row["reviewer"]} — selló v{row["sealed_version"]} — '
             f'{"documento completo" if row["covers_all"] else ", ".join(row["covered_sections"])}',
             9)
        line(f'  Firma Ed25519 re-verificada al emitir: '
             f'{"VÁLIDA" if row["signature_valid_now"] else "INVÁLIDA"}',
             9, bold=not row['signature_valid_now'])
    y -= 0.4 * cm

    line('VERIFICACIÓN OFFLINE (sin depender de Versiona)', 12, bold=True, gap=0.8)
    line('1. Tome el JSON canónico de cada sello (anexo) y serialícelo con', 9)
    line('   claves ordenadas y sin espacios (sort_keys, separators=(",",":")).', 9)
    line('2. Verifique la firma (base64) con Ed25519 y la clave pública anexa.', 9)
    line('3. Compare el sha256 del PDF original con el registrado arriba.', 9)
    line(f'Clave pública Ed25519 (base64): {public_key}', 8)
    y -= 0.4 * cm

    line('ANEXO — PAYLOADS CANÓNICOS Y FIRMAS', 12, bold=True, gap=0.8)
    for row in seals:
        payload_json = json.dumps(row['payload'], sort_keys=True,
                                  separators=(',', ':'), ensure_ascii=False)
        line(f'Sello de {row["reviewer"]} (key_id {row["key_id"]}):', 9, bold=True)
        for start in range(0, len(payload_json), 100):
            line(payload_json[start:start + 100], 7, gap=0.4)
        line(f'Firma: {row["signature"]}', 7, gap=0.7)

    page.save()
    return buffer.getvalue()


@transaction.atomic
def issue_certificate(version: DocumentVersion, issued_by, request=None) -> Certificate:
    if not version.is_approved:
        raise DomainError('La constancia solo se emite sobre una versión APROBADA.', 409)
    org = version.document.project.organization
    seals = _gather_seals(version)
    if not seals:
        raise DomainError('La versión no tiene sellos vigentes que certificar.', 409)
    invalid = [row['reviewer'] for row in seals if not row['signature_valid_now']]
    if invalid:
        raise DomainError(
            f'Firma(s) que no verifican: {", ".join(invalid)}. No se emite constancia.', 409
        )

    # The serial counts committed rows: the organization row serializes every
    # issuance in it, so a contender counts only after the previous commit.
    Organization.objects.select_for_update().only('pk').get(pk=org.pk)
    serial = _serial_for(org)
    public_key = signing.public_key_b64()
    pdf_bytes = _render_pdf(serial, version, seals, public_key, issued_by)
    # The object key belongs to this certificate alone: no serial collision can
    # replace the PDF of a certificate that is already issued (E4-F03).
    public_id = uuid7()
    pdf_key = (f'{storage_service._env_prefix()}/orgs/{org.public_id}/certificates/'
               f'{serial}-{public_id}.pdf')
    storage_service.put_bytes(pdf_key, pdf_bytes, 'application/pdf')

    certificate = Certificate.objects.create(
        public_id=public_id,
        organization=org,
        document_version=version,
        serial=serial,
        issued_by=issued_by,
        snapshot={
            'serial': serial,
            'issued_at': timezone.now().isoformat(),
            'version_number': version.number,
            'version_sha256': version.sha256,
            'pdf_sha256': hashlib.sha256(pdf_bytes).hexdigest(),
            'public_key': public_key,
            'seals': seals,
        },
        pdf_key=pdf_key,
    )
    audit.record(
        org=org, project=version.document.project, actor=issued_by,
        event_type='certificate.issued', obj=certificate,
        payload={'serial': serial, 'version': version.number,
                 'seals': len(seals)},
        request=request,
    )
    return certificate
