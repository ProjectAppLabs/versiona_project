"""Comparison endpoints (flow E1 — docs/plan/03 §3)."""

from django.http import Http404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.permissions import require_project_role, resolve_effective_role
from documents.models import Document, DocumentVersion
from documents.services.version_service import DomainError

from .models import Comparison
from .serializers import (
    ComparisonCreateSerializer,
    ComparisonDetailSerializer,
    SectionDiffDetailSerializer,
)
from .services import build_comparison, validate_pair


def _history_lock_response(*versions):
    """DP-04: a diff reveals both of its versions, so each one must pass the
    plan's history lock. Returns the 402 to answer, or None when all pass."""
    from billing.services import check_history_access

    try:
        for version in versions:
            check_history_access(version)
    except DomainError as exc:
        return Response({'error': str(exc), 'upgrade': True}, status=exc.status_code)
    return None


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def document_comparisons(request, doc):
    document: Document = request.resolved_object

    if request.method == 'GET':
        queryset = Comparison.objects.filter(document=document).select_related(
            'from_version', 'to_version'
        )[:25]
        return Response(
            {'results': ComparisonDetailSerializer(queryset, many=True).data}
        )

    serializer = ComparisonCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    versions = {
        str(version.public_id): version
        for version in DocumentVersion.objects.filter(
            document=document,
            public_id__in=[
                serializer.validated_data['from_version'],
                serializer.validated_data['to_version'],
            ],
        )
    }
    from_version = versions.get(str(serializer.validated_data['from_version']))
    to_version = versions.get(str(serializer.validated_data['to_version']))
    if from_version is None or to_version is None:
        raise Http404

    locked = _history_lock_response(from_version, to_version)
    if locked is not None:
        return locked

    try:
        # Guards first: a stale cache is never served for an uncomparable pair.
        validate_pair(document, from_version, to_version)
        existing = Comparison.objects.filter(
            from_version=from_version, to_version=to_version, status=Comparison.Status.DONE
        ).first()
        comparison = existing or build_comparison(
            document, from_version, to_version, request.user, request=request
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)

    return Response(
        ComparisonDetailSerializer(comparison).data,
        # 200 = served from cache; 201 = freshly computed (docs/plan/03 §3).
        status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED,
    )


def _load_comparison(request, cmp_id):
    comparison = (
        Comparison.objects.filter(public_id=cmp_id)
        .select_related('document__project__organization', 'from_version', 'to_version')
        .first()
    )
    if comparison is None:
        raise Http404
    project = comparison.document.project
    role = resolve_effective_role(request.user, project)
    if role is None:
        raise Http404
    return comparison


@api_view(['GET'])
def comparison_detail(request, cmp):
    comparison = _load_comparison(request, cmp)
    locked = _history_lock_response(comparison.from_version, comparison.to_version)
    if locked is not None:
        return locked
    return Response(ComparisonDetailSerializer(comparison).data)


@api_view(['GET'])
def comparison_section_diff(request, cmp, sec):
    comparison = _load_comparison(request, cmp)
    locked = _history_lock_response(comparison.from_version, comparison.to_version)
    if locked is not None:
        return locked
    diff = comparison.diffs.filter(stable_key=sec).first()
    if diff is None:
        raise Http404
    return Response(SectionDiffDetailSerializer(diff).data)


@api_view(['GET'])
@require_project_role('viewer')
def project_saved_comparisons(request, proj):
    from .models import SavedComparison

    rows = SavedComparison.objects.filter(project=request.project).select_related(
        'comparison__from_version', 'comparison__to_version',
        'comparison__document', 'created_by',
    )
    return Response({'results': [
        {
            'public_id': str(row.public_id),
            'name': row.name,
            'created_by': row.created_by.email,
            'created_at': row.created_at,
            'document_title': row.comparison.document.title,
            'summary': row.comparison.summary.get('text', ''),
            'link': (f'/projects/{request.project.public_id}/documents/'
                     f'{row.comparison.document.public_id}/compare/'
                     f'{row.comparison.from_version.public_id}/'
                     f'{row.comparison.to_version.public_id}'),
        }
        for row in rows
    ]})


@api_view(['POST', 'DELETE'])
def comparison_save(request, cmp):
    """E2: name (POST {name}) or unsave (DELETE) a comparison."""
    from core.permissions import resolve_effective_role

    from .models import SavedComparison

    comparison = _load_comparison(request, cmp)
    project = comparison.document.project
    role = resolve_effective_role(request.user, project)
    if role == 'viewer' and request.method != 'GET':
        raise Http404  # read-only role

    if request.method == 'DELETE':
        deleted, _ = SavedComparison.objects.filter(
            project=project, comparison=comparison
        ).delete()
        return Response({'deleted': bool(deleted)})

    name = ((request.data or {}).get('name') or '').strip()
    if not name:
        return Response({'error': 'La comparación guardada necesita un nombre.'}, status=400)
    if SavedComparison.objects.filter(project=project, name=name).exists():
        return Response({'error': f'Ya existe una comparación guardada "{name}".'}, status=409)
    saved = SavedComparison.objects.create(
        project=project, comparison=comparison, name=name, created_by=request.user
    )
    return Response({'public_id': str(saved.public_id), 'name': saved.name}, status=201)
