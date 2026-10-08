"""Document & version endpoints (flows C1/C2/C3/C4 — docs/plan/03 §3)."""

from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from core.permissions import require_project_role

from .models import Document, DocumentVersion
from .queries import prepare_document_list_versions, with_document_list_data
from .serializers import (
    DocumentCreateSerializer,
    DocumentListSerializer,
    UploadCompleteSerializer,
    VersionDetailSerializer,
    VersionListSerializer,
    VersionMessageSerializer,
)
from .services import trash_service, version_service
from .services.version_service import DomainError


class UploadThrottle(UserRateThrottle):
    scope = 'upload'


def _domain_error(exc: DomainError) -> Response:
    return Response({'error': str(exc)}, status=exc.status_code)


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def project_documents(request, proj):
    if request.method == 'GET':
        queryset = with_document_list_data(
            Document.objects.filter(project=request.project).order_by('-updated_at')
        )
        search = request.query_params.get('q', '').strip()
        if search:
            queryset = queryset.filter(title__icontains=search)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request)
        prepare_document_list_versions(page)
        return paginator.get_paginated_response(
            DocumentListSerializer(page, many=True).data
        )

    if request.effective_role not in ('editor', 'admin'):
        return Response({'error': 'Se requiere rol editor.'}, status=403)
    serializer = DocumentCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        document = version_service.create_document(
            request.project, serializer.validated_data['title'], request.user, request
        )
    except DomainError as exc:
        return _domain_error(exc)
    return Response(DocumentListSerializer(document).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'DELETE'])
@require_project_role('viewer')
def document_detail(request, doc):
    document: Document = request.resolved_object

    if request.method == 'GET':
        return Response(DocumentListSerializer(document).data)

    if request.effective_role != 'admin':
        return Response({'error': 'Se requiere rol admin.'}, status=403)
    try:
        trash_service.trash_document(document, request.user, request)
    except DomainError as exc:
        return _domain_error(exc)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@require_project_role('admin', include_trashed=True)
def document_restore(request, doc):
    document: Document = request.resolved_object
    try:
        trash_service.restore_document(document, request.user, request)
    except DomainError as exc:
        return _domain_error(exc)
    return Response(DocumentListSerializer(document).data)


@api_view(['GET'])
@require_project_role('viewer')
def document_versions(request, doc):
    """Timeline C3-F01: alive versions + trashed tombstones (C4-F01)."""
    document: Document = request.resolved_object
    from .queries import with_version_list_data

    queryset = with_version_list_data(
        DocumentVersion.all_objects.filter(document=document).order_by('-number')
    )
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(VersionListSerializer(page, many=True).data)


@api_view(['POST'])
@require_project_role('editor')
@throttle_classes([UploadThrottle])
def upload_intent(request, doc):
    document: Document = request.resolved_object
    try:
        intent = version_service.create_upload_intent(document, request.user)
    except DomainError as exc:
        return _domain_error(exc)
    return Response({
        'upload_id': intent.upload_id,
        'url': intent.url,
        'max_bytes': intent.max_bytes,
    })


@api_view(['POST'])
@require_project_role('editor')
def upload_complete(request, doc):
    document: Document = request.resolved_object
    serializer = UploadCompleteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        version, job = version_service.complete_upload(
            document,
            serializer.validated_data['upload_id'],
            serializer.validated_data.get('message', ''),
            request.user,
            request,
        )
    except DomainError as exc:
        return _domain_error(exc)
    return Response(
        {'version': VersionListSerializer(version).data, 'job_id': str(job.public_id)},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['GET', 'PATCH', 'DELETE'])
@require_project_role('viewer')
def version_detail(request, ver):
    version: DocumentVersion = request.resolved_object

    if request.method == 'GET':
        data = VersionDetailSerializer(version).data
        # The screen decides what to render by role (seal bar, plan card).
        data['effective_role'] = request.effective_role
        return Response(data)

    if request.method == 'PATCH':
        is_author = version.author_id == request.user.pk
        if not (request.effective_role == 'admin' or
                (request.effective_role == 'editor' and is_author)):
            return Response({'error': 'Solo el autor o un admin editan el mensaje.'}, status=403)
        serializer = VersionMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            version_service.edit_message(
                version, serializer.validated_data['message'], request.user, request
            )
        except DomainError as exc:
            return _domain_error(exc)
        return Response(VersionListSerializer(version).data)

    # DELETE → trash (C4)
    is_author = version.author_id == request.user.pk
    if not (request.effective_role == 'admin' or
            (request.effective_role == 'editor' and is_author)):
        return Response({'error': 'Solo el autor o un admin eliminan un borrador.'}, status=403)
    try:
        trash_service.trash_version(version, request.user, request)
    except DomainError as exc:
        return _domain_error(exc)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@require_project_role('editor', include_trashed=True)
def version_restore(request, ver):
    version: DocumentVersion = request.resolved_object
    is_author = version.author_id == request.user.pk
    if not (request.effective_role == 'admin' or is_author):
        return Response({'error': 'Solo el autor o un admin restauran.'}, status=403)
    try:
        trash_service.restore_version(version, request.user, request)
    except DomainError as exc:
        return _domain_error(exc)
    return Response(VersionListSerializer(version).data)


@api_view(['GET'])
@require_project_role('viewer')
def version_download(request, ver):
    version: DocumentVersion = request.resolved_object
    from billing.services import check_history_access

    try:
        check_history_access(version)
    except DomainError as exc:
        return Response({'error': str(exc), 'upgrade': True}, status=exc.status_code)
    url = version_service.download_url(version, request.user, request)
    return Response({'url': url})


@api_view(['GET'])
@require_project_role('viewer')
def version_file(request, ver):
    """Inline presigned URL for the in-app viewer (react-pdf)."""
    version: DocumentVersion = request.resolved_object
    from .services import storage_service
    url = storage_service.presign_view(version.file_key, 'application/pdf')
    return Response({'url': url})


@api_view(['GET'])
@require_project_role('viewer')
def version_sections(request, ver):
    version: DocumentVersion = request.resolved_object
    from .serializers import SectionSerializer
    sections = version.section_versions.select_related('section').order_by('order_index')
    return Response({'results': SectionSerializer(sections, many=True).data})
