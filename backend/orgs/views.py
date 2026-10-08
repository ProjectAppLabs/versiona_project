"""Org endpoints (It1 slice: my orgs + unified trash — docs/plan/03 §3)."""

from itertools import chain

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.permissions import require_org_role

from .models import OrganizationMembership


@api_view(['GET'])
def my_orgs(request):
    memberships = (
        OrganizationMembership.objects.filter(user=request.user, is_active=True)
        .select_related('organization')
        # The team workspace is the daily driver: it comes first, the
        # personal one after (deterministic default for orgStore).
        .order_by('-organization__kind', 'organization__name')
    )
    return Response({
        'results': [
            {
                'public_id': str(m.organization.public_id),
                'name': m.organization.name,
                'slug': m.organization.slug,
                'kind': m.organization.kind,
                'role': m.role,
            }
            for m in memberships
        ]
    })


@api_view(['GET'])
@require_org_role('admin')
def org_trash(request, org):
    """Unified trash list (kit 3 — B4/C4): projects, documents, draft versions."""
    from documents.models import Document, DocumentVersion
    from projects.models import Project
    from projects.serializers import TrashItemSerializer

    projects = (
        Project.all_objects.trashed().filter(organization=request.org)
        .select_related('organization', 'deleted_by')
    )
    documents = Document.all_objects.trashed().filter(
        project__organization=request.org, project__deleted_at__isnull=True
    ).select_related('project', 'deleted_by')
    versions = DocumentVersion.all_objects.trashed().filter(
        document__project__organization=request.org,
        document__deleted_at__isnull=True,
        document__project__deleted_at__isnull=True,
    ).select_related('document__project', 'deleted_by')

    def item(obj, type_name, name, context):
        return {
            'type': type_name,
            'public_id': obj.public_id,
            'name': name,
            'context': context,
            'deleted_at': obj.deleted_at,
            'deleted_by': obj.deleted_by.email if obj.deleted_by else None,
            'purge_after': obj.purge_after,
        }

    items = list(chain(
        (item(p, 'project', p.name, p.organization.name) for p in projects),
        (item(d, 'document', d.title, d.project.name) for d in documents),
        (item(v, 'version', f'{v.document.title} · v{v.number}', v.document.project.name)
         for v in versions),
    ))
    items.sort(key=lambda entry: entry['deleted_at'], reverse=True)
    return Response({'results': TrashItemSerializer(items, many=True).data})


@api_view(['GET', 'POST'])
def my_onboarding(request):
    """A1 wizard: GET the state; POST {org_name} renames the personal org and
    seeds the sample project — the response carries the wow link."""
    from documents.services.version_service import DomainError
    from orgs.onboarding import complete_onboarding, onboarding_state

    if request.method == 'GET':
        return Response(onboarding_state(request.user))
    try:
        state = complete_onboarding(
            request.user, (request.data or {}).get('org_name', ''), request=request
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(state, status=201)


@api_view(['GET'])
@permission_classes([AllowAny])
def invitation_state(request, token):
    """Public: what the /invite/[token] landing may show pre-auth."""
    from documents.services.version_service import DomainError
    from orgs.invitations import invitation_public_state

    try:
        return Response(invitation_public_state(token))
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)


@api_view(['POST'])
def invitation_accept(request, token):
    from documents.services.version_service import DomainError
    from orgs.invitations import accept_invitation

    try:
        return Response(accept_invitation(token, request.user, request=request))
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)


@api_view(['GET'])
def org_usage(request, org):
    """F2: usage vs plan limits with 80% warnings (member-visible)."""
    from billing.services import usage_report
    from core.permissions import resolve_org_role

    from .models import Organization

    organization = Organization.objects.filter(public_id=org).first()
    if organization is None or resolve_org_role(request.user, organization) is None:
        from django.http import Http404

        raise Http404
    return Response(usage_report(organization))
