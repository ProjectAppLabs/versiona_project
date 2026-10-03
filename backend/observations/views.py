"""Observation endpoints (D3) with bounded pages and progressive content."""

from django.http import Http404
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from core.permissions import require_project_role, resolve_effective_role
from documents.models import DocumentVersion
from documents.services.version_service import DomainError

from . import queries, services
from .models import Observation, ObservationAnchor, ObservationReply
from .pagination import page_by_created_at, page_by_version_number


class ObservationCreateSerializer(serializers.Serializer):
    body = serializers.CharField()
    section_key = serializers.CharField(required=False, allow_blank=True, default='')
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    quads = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    snippet = serializers.CharField(required=False, allow_blank=True, default='')


def _requested_version(request):
    raw = request.query_params.get('version')
    if raw is None:
        return None
    return serializers.UUIDField().run_validation(raw)


def _summary(observation, *, version_id=None):
    row = queries.observation_rows(
        Observation.objects.filter(pk=observation.pk), version_id=version_id,
    ).get()
    return queries.observation_summary(row)


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def version_observations(request, ver):
    """Page document threads or create a thread anchored to this version."""
    version: DocumentVersion = request.resolved_object

    if request.method == 'GET':
        status_filter = request.query_params.get('status', 'all')
        if status_filter not in ('all', 'active', *Observation.Status.values):
            raise ValidationError({'status': 'El filtro de estado no es válido.'})
        queryset = Observation.objects.filter(document=version.document)
        if status_filter == 'active':
            queryset = queryset.exclude(status=Observation.Status.RESOLVED)
        elif status_filter != 'all':
            queryset = queryset.filter(status=status_filter)
        rows, next_cursor = page_by_created_at(
            queries.observation_rows(queryset), cursor=request.query_params.get('cursor'),
            scope=f'observations:{version.public_id}:{status_filter}',
        )
        anchors = {
            row['observation_id']: row
            for row in queries.anchor_rows(ObservationAnchor.objects.filter(
                observation_id__in=[row['pk'] for row in rows], document_version=version,
            ))
        }
        results = []
        for row in rows:
            anchor = anchors.get(row['pk'])
            results.append(queries.observation_summary(
                row,
                current_anchor=queries.anchor_summary(anchor, row['public_id'])
                if anchor else None,
            ))
        return Response({'results': results, 'next_cursor': next_cursor})

    if request.effective_role not in ('reviewer', 'admin'):
        raise Http404
    serializer = ObservationCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        observation = services.create_observation(
            version, request.user,
            body=serializer.validated_data['body'],
            section_key=serializer.validated_data['section_key'],
            page=serializer.validated_data['page'],
            quads=serializer.validated_data['quads'],
            snippet=serializer.validated_data['snippet'],
            request=request,
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(
        _summary(observation, version_id=version.public_id), status=status.HTTP_201_CREATED,
    )


def _load_observation(request, obs):
    observation = (
        Observation.objects.filter(public_id=obs)
        .select_related('document__project__organization', 'author', 'section')
        .defer('body')
        .first()
    )
    if observation is None:
        raise Http404
    role = resolve_effective_role(request.user, observation.document.project)
    if role is None:
        raise Http404
    request.effective_role = role
    return observation


@api_view(['GET'])
def observation_detail(request, obs):
    observation = _load_observation(request, obs)
    return Response(_summary(observation, version_id=_requested_version(request)))


@api_view(['GET', 'POST'])
def observation_reply(request, obs):
    observation = _load_observation(request, obs)
    if request.method == 'GET':
        rows, next_cursor = page_by_created_at(
            queries.reply_rows(ObservationReply.objects.filter(observation=observation)),
            cursor=request.query_params.get('cursor'), scope=f'replies:{observation.public_id}',
        )
        return Response({
            'results': [queries.reply_summary(row, observation.public_id) for row in rows],
            'next_cursor': next_cursor,
        })

    if request.effective_role == 'viewer':
        raise Http404  # read-only role
    body = (request.data or {}).get('body', '')
    try:
        reply = services.reply_to_observation(observation, request.user, body, request=request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    row = queries.reply_rows(ObservationReply.objects.filter(pk=reply.pk)).get()
    return Response({
        'reply': queries.reply_summary(row, observation.public_id), 'status': observation.status,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def observation_status(request, obs):
    observation = _load_observation(request, obs)
    if request.effective_role == 'viewer':
        raise Http404
    version_id = _requested_version(request)
    new_status = (request.data or {}).get('status', '')
    try:
        services.set_observation_status(observation, request.user, new_status, request=request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(_summary(observation, version_id=version_id))


@api_view(['GET'])
def observation_anchors(request, obs):
    observation = _load_observation(request, obs)
    rows, next_cursor = page_by_version_number(
        queries.anchor_rows(ObservationAnchor.objects.filter(observation=observation)),
        cursor=request.query_params.get('cursor'), scope=f'anchors:{observation.public_id}',
    )
    return Response({
        'results': [queries.anchor_summary(row, observation.public_id) for row in rows],
        'next_cursor': next_cursor,
    })


def _content_response(request, queryset, expression):
    # MySQL LONGTEXT cannot exceed this character count. Reject an oversized
    # offset before binding it as a SQL integer, alongside other invalid offsets.
    raw_offset = request.query_params.get('offset', '0')
    if not raw_offset.isascii() or not raw_offset.isdecimal():
        raise ValidationError({'offset': 'La posición debe ser un entero no negativo.'})
    offset = serializers.IntegerField(min_value=0, max_value=2 ** 32 - 1).run_validation(raw_offset)
    fragment = queries.content_fragment(queryset, expression, offset)
    if fragment is None:
        raise Http404
    if offset > fragment['content_length']:
        raise ValidationError({'offset': 'La posición está después del final del contenido.'})
    content = fragment['content_piece']
    next_offset = offset + len(content)
    eof = next_offset >= fragment['content_length']
    return Response({
        'content': content, 'offset': offset, 'next_offset': None if eof else next_offset,
        'eof': eof,
    })


@api_view(['GET'])
def observation_content(request, obs):
    observation = _load_observation(request, obs)
    return _content_response(request, Observation.objects.filter(pk=observation.pk), 'body')


@api_view(['GET'])
def observation_reply_content(request, obs, reply):
    observation = _load_observation(request, obs)
    return _content_response(request, ObservationReply.objects.filter(
        observation=observation, public_id=reply,
    ), 'body')


@api_view(['GET'])
def observation_anchor_content(request, obs, version_number):
    observation = _load_observation(request, obs)
    return _content_response(request, ObservationAnchor.objects.filter(
        observation=observation, document_version__number=version_number,
    ), queries.JsonText('quads'))
