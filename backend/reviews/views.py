"""Seal endpoints (D4) + seal plan (D5 coordinator) — docs/plan/03 §3."""

from django.http import Http404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.permissions import require_project_role
from documents.services.version_service import DomainError

from .models import Seal, SealValidityRecord
from .serializers import (
    SealCreateSerializer,
    SealPlanConfirmSerializer,
    SealSerializer,
    SealValidityRecordSerializer,
)
from .services import seal_service, signing


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def version_seals(request, ver):
    """GET: seals + their validity records for this version. POST (reviewer+):
    place a seal over sections or the whole document."""
    version = request.resolved_object

    if request.method == 'GET':
        seals = (
            Seal.objects.filter(document_version=version)
            .select_related('reviewer', 'document_version')
            .prefetch_related('covered_sections__section')
        )
        incoming = (
            SealValidityRecord.objects.filter(to_document_version=version)
            .select_related(
                'seal__reviewer', 'seal__document_version', 'decided_by',
                'to_document_version',
            )
            .prefetch_related('seal__covered_sections__section')
        )
        return Response({
            'seals': SealSerializer(seals, many=True).data,
            'validity_records': SealValidityRecordSerializer(incoming, many=True).data,
        })

    if request.effective_role not in ('reviewer', 'admin'):
        raise Http404  # I12: outsiders and viewers see no write surface

    serializer = SealCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        seal = seal_service.create_seal(
            version,
            request.user,
            covers_all=serializer.validated_data['covers_all'],
            section_keys=serializer.validated_data['section_keys'],
            request=request,
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(SealSerializer(seal).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@require_project_role('reviewer')
def seal_revoke(request, ver, seal_id):
    version = request.resolved_object
    seal = Seal.objects.filter(document_version=version, public_id=seal_id).first()
    if seal is None:
        raise Http404
    try:
        seal_service.revoke_seal(seal, request.user, request=request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(SealSerializer(seal).data)


@api_view(['GET'])
@require_project_role('viewer')
def seal_verify(request, ver, seal_id):
    """Re-verifies the Ed25519 signature server-side and returns everything a
    third party needs to verify it OFFLINE (payload, signature, public key)."""
    version = request.resolved_object
    seal = Seal.objects.filter(document_version=version, public_id=seal_id).first()
    if seal is None:
        raise Http404
    valid = signing.verify(seal.signed_payload, seal.signature)
    return Response({
        'signature_valid': valid,
        'binds_version_sha256': seal.signed_payload.get('version_sha256') == version.sha256,
        'payload': seal.signed_payload,
        'signature': seal.signature,
        'key_id': seal.key_id,
        'public_key': signing.public_key_b64(),
        'algorithm': 'Ed25519',
    })


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def version_seal_plan(request, ver):
    """D5 coordinator mode: GET lists pending records; POST (admin — the
    `can_confirm_seal_plan` capability, DP-07) confirms the plan."""
    version = request.resolved_object
    if request.method == 'GET':
        pending = (
            SealValidityRecord.objects.filter(
                to_document_version=version,
                decision=SealValidityRecord.Decision.PENDING,
            )
            .select_related('seal__reviewer', 'seal__document_version', 'to_document_version')
            .prefetch_related('seal__covered_sections__section')
        )
        return Response(
            {'pending': SealValidityRecordSerializer(pending, many=True).data}
        )

    if request.effective_role != 'admin':
        raise Http404
    serializer = SealPlanConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        resolved = seal_service.confirm_seal_plan(
            version, request.user, serializer.validated_data['decisions'], request=request
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(
        {'resolved': SealValidityRecordSerializer(resolved, many=True).data}
    )


@api_view(['GET'])
def seal_public_key(request, key_id):
    """Public key material for offline verification (E4 groundwork)."""
    if key_id != signing.key_id():
        raise Http404
    return Response({
        'key_id': key_id,
        'algorithm': 'Ed25519',
        'public_key': signing.public_key_b64(),
    })


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def version_certificates(request, ver):
    """E4: GET certificates issued for this version; POST (admin) issues one,
    re-verifying every signature."""
    from documents.services import storage_service

    from .models import Certificate
    from .services.certificate_service import issue_certificate

    version = request.resolved_object

    if request.method == 'GET':
        rows = Certificate.objects.filter(document_version=version).select_related('issued_by')
        return Response({'results': [
            {'public_id': str(c.public_id), 'serial': c.serial,
             'issued_by': c.issued_by.email, 'created_at': c.created_at,
             'seals': len(c.snapshot.get('seals', []))}
            for c in rows
        ]})

    if request.effective_role != 'admin':
        raise Http404
    try:
        certificate = issue_certificate(version, request.user, request=request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({
        'public_id': str(certificate.public_id),
        'serial': certificate.serial,
        'download_url': storage_service.presign_download(
            certificate.pdf_key, f'{certificate.serial}.pdf'
        ),
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@require_project_role('viewer')
def certificate_download(request, ver, cert_id):
    from documents.services import storage_service

    from .models import Certificate

    certificate = Certificate.objects.filter(
        document_version=request.resolved_object, public_id=cert_id
    ).first()
    if certificate is None:
        raise Http404
    return Response({
        'url': storage_service.presign_download(
            certificate.pdf_key, f'{certificate.serial}.pdf'
        ),
        'snapshot': certificate.snapshot,
    })
