"""Project endpoints (flows B1, B2-mínimo, B4 — docs/plan/03 §3)."""

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from audit import services as audit
from core.permissions import require_org_role, require_project_role, resolve_org_role
from documents.services.trash_service import (
    archive_project,
    restore_project,
    trash_project,
    unarchive_project,
)
from documents.services.version_service import DomainError

from .models import Project, ProjectMembership
from .serializers import ProjectCreateUpdateSerializer, ProjectDetailSerializer, ProjectListSerializer


def _visible_projects(user, org):
    """Scoping I12: org owners/admins see every project; members see theirs."""
    org_role = resolve_org_role(user, org)
    queryset = Project.objects.filter(organization=org)
    if org_role not in ('owner', 'admin'):
        queryset = queryset.filter(memberships__user=user)
    return queryset.annotate(
        document_count=Count('documents', filter=Q(documents__deleted_at__isnull=True), distinct=True)
    ).order_by('-updated_at')


@api_view(['GET', 'POST'])
@require_org_role('member')
def org_projects(request, org):
    if request.method == 'GET':
        queryset = _visible_projects(request.user, request.org)
        search = request.query_params.get('q', '').strip()
        if search:
            from django.db.models import Exists, OuterRef

            from documents.models import SectionVersion
            from documents.queries import newer_alive_versions
            from documents.search import boolean_query

            # B2-A02/A03: match by name OR by CONTENT of each document's
            # current version (MySQL FULLTEXT over the stemmed section text).
            content_match = SectionVersion.objects.filter(
                document_version__document__project=OuterRef('pk'),
                document_version__document__deleted_at__isnull=True,
                document_version__deleted_at__isnull=True,
                search_text__fts=boolean_query(search),
            ).filter(~Exists(newer_alive_versions(
                OuterRef('document_version__document_id'),
                OuterRef('document_version__number'),
            )))
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(Exists(content_match))
            )
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request)
        roles = {
            membership.project_id: membership.role
            for membership in ProjectMembership.objects.filter(
                user=request.user, project__in=[p.pk for p in page]
            )
        }
        if request.org_role in ('owner', 'admin'):
            roles = {p.pk: 'admin' for p in page}
        serializer = ProjectListSerializer(page, many=True, context={'roles_by_project': roles})
        return paginator.get_paginated_response(serializer.data)

    serializer = ProjectCreateUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    name = serializer.validated_data['name'].strip()
    if not name:
        return Response({'error': 'El nombre es obligatorio.'}, status=400)
    from billing.services import check_project_limit

    try:
        check_project_limit(request.org)
    except DomainError as exc:
        return Response({'error': str(exc), 'upgrade': True}, status=exc.status_code)
    base = slugify(name)[:150] or 'proyecto'
    slug = base
    suffix = 1
    while Project.objects.filter(organization=request.org, slug=slug).exists():
        suffix += 1
        slug = f'{base}-{suffix}'
    project = Project.objects.create(
        organization=request.org,
        name=name,
        slug=slug,
        description=serializer.validated_data.get('description', ''),
    )
    ProjectMembership.objects.get_or_create(
        project=project, user=request.user,
        defaults={'role': ProjectMembership.Role.ADMIN},
    )
    audit.record(org=request.org, project=project, actor=request.user,
                 event_type='project.created', obj=project,
                 payload={'name': name}, request=request)
    project.document_count = 0
    return Response(
        ProjectDetailSerializer(project, context={'roles_by_project': {project.pk: 'admin'}}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def project_config(request, proj):
    """B3: GET the current pinned-able config; POST (admin) creates a NEW
    version — I8 makes retroactivity structurally impossible."""
    from django.http import Http404 as _Http404

    from projects.models import ProjectConfigVersion
    from projects.services import config_service
    from documents.services.version_service import DomainError

    if request.effective_role != 'admin':
        raise _Http404
    if request.method == 'GET':
        config = ProjectConfigVersion.current_for(request.project)
        return Response({
            'number': config.number,
            'd5_mode': config.d5_mode,
            'approval_policy': config.approval_policy,
            'checklist': config.checklist,
            'section_owners': config.section_owners,
            'history_count': ProjectConfigVersion.objects.filter(
                project=request.project
            ).count(),
        })

    if request.effective_role != 'admin':
        raise _Http404
    payload = request.data or {}
    try:
        config = config_service.update_config(
            request.project, request.user,
            checklist=payload.get('checklist'),
            d5_mode=payload.get('d5_mode'),
            approval_policy=payload.get('approval_policy'),
            section_owners=payload.get('section_owners'),
            request=request,
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'number': config.number}, status=201)


@api_view(['POST'])
@require_project_role('admin')
def project_apply_template(request, proj):
    from checks.models import ChecklistTemplate
    from django.http import Http404 as _Http404

    from projects.services import config_service
    from documents.services.version_service import DomainError

    template = ChecklistTemplate.objects.filter(
        organization=request.project.organization,
        public_id=(request.data or {}).get('template'),
    ).first()
    if template is None:
        raise _Http404
    try:
        config = config_service.apply_template(
            request.project, request.user, template, request=request
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'number': config.number, 'checklist': config.checklist}, status=201)


@api_view(['GET', 'POST'])
@require_project_role('admin')
def project_invitations(request, proj):
    """A2: list + create invitations (admin)."""
    from django.http import Http404 as _Http404  # noqa: F401

    from orgs.invitations import create_invitation
    from orgs.models import Invitation

    if request.method == 'GET':
        rows = Invitation.objects.filter(project=request.project).select_related('invited_by')
        return Response({'results': [
            {'public_id': str(i.public_id), 'email': i.email, 'role': i.role,
             'status': i.status, 'invited_by': i.invited_by.email,
             'expires_at': i.expires_at, 'created_at': i.created_at}
            for i in rows
        ]})

    payload = request.data or {}
    try:
        invitation = create_invitation(
            request.project, request.user,
            email=payload.get('email', ''), role=payload.get('role', ''),
            request=request,
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'public_id': str(invitation.public_id), 'email': invitation.email,
                     'role': invitation.role, 'status': invitation.status},
                    status=status.HTTP_201_CREATED)


@api_view(['POST'])
@require_project_role('admin')
def project_invitation_revoke(request, proj, inv):
    from django.http import Http404 as _Http404

    from orgs.invitations import revoke_invitation
    from orgs.models import Invitation

    invitation = Invitation.objects.filter(project=request.project, public_id=inv).first()
    if invitation is None:
        raise _Http404
    try:
        revoke_invitation(invitation, request.user, request=request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response({'status': 'revoked'})


@api_view(['GET'])
@require_project_role('viewer')
def project_report(request, proj):
    """Kit 4: the project status report — documents, versions, seals valid at
    the latest version, open observations and check summaries."""
    from .queries import project_report_documents

    rows = project_report_documents(request.project)
    return Response({
        'project': request.project.name,
        'status': request.project.status,
        'generated_at': timezone.now(),
        'documents': rows,
    })


@api_view(['GET'])
@require_project_role('viewer')
def project_members(request, proj):
    """Members with their effective role — feeds the reviewer picker (D1)."""
    from projects.models import ProjectMembership

    memberships = ProjectMembership.objects.filter(
        project=request.project
    ).select_related('user')
    return Response({'results': [
        {'id': m.user_id, 'email': m.user.email,
         'first_name': m.user.first_name, 'role': m.role}
        for m in memberships
    ]})


@api_view(['GET', 'PATCH', 'DELETE'])
@require_project_role('viewer')
def project_detail(request, proj):
    project = request.project

    if request.method == 'GET':
        project.document_count = project.documents.count()
        return Response(ProjectDetailSerializer(
            project, context={'roles_by_project': {project.pk: request.effective_role}}
        ).data)

    if request.effective_role != 'admin':
        return Response({'error': 'Se requiere rol admin.'}, status=403)

    if request.method == 'PATCH':
        serializer = ProjectCreateUpdateSerializer(project, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {'name': project.name, 'description': project.description}
        serializer.save()
        audit.record(org=request.org, project=project, actor=request.user,
                     event_type='project.updated', obj=project,
                     payload={'before': before}, request=request)
        project.document_count = project.documents.count()
        return Response(ProjectDetailSerializer(
            project, context={'roles_by_project': {project.pk: request.effective_role}}
        ).data)

    # DELETE → trash (two-step confirmation, B4-F02)
    try:
        trash_project(project, request.data.get('confirm_name', ''), request.user, request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(status=status.HTTP_204_NO_CONTENT)


def _project_action(request, action):
    try:
        action(request.project, request.user, request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    request.project.refresh_from_db()
    return Response(ProjectDetailSerializer(
        request.project, context={'roles_by_project': {request.project.pk: 'admin'}}
    ).data)


@api_view(['POST'])
@require_project_role('admin', include_trashed=True)
def project_restore(request, proj):
    return _project_action(request, restore_project)


@api_view(['POST'])
@require_project_role('admin')
def project_archive(request, proj):
    return _project_action(request, archive_project)


@api_view(['POST'])
@require_project_role('admin', include_trashed=True)
def project_unarchive(request, proj):
    return _project_action(request, unarchive_project)
