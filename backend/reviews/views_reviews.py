"""Review request endpoints (D1) + assisted-review context (D2)."""

from django.http import Http404
from django.db.models import Exists, OuterRef, Q
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.permissions import require_project_role
from documents.services.version_service import DomainError
from orgs.models import OrganizationMembership
from projects.models import ProjectMembership

from .models import ReviewAssignment, ReviewRequest
from .services import review_service


class AssignmentSerializer(serializers.ModelSerializer):
    reviewer_email = serializers.EmailField(source='reviewer.email', read_only=True)

    class Meta:
        model = ReviewAssignment
        fields = ('reviewer_email', 'scope', 'status', 'completed_at')


class ReviewRequestSerializer(serializers.ModelSerializer):
    requested_by_email = serializers.EmailField(source='requested_by.email', read_only=True)
    version_number = serializers.IntegerField(source='document_version.number', read_only=True)
    assignments = AssignmentSerializer(many=True, read_only=True)

    class Meta:
        model = ReviewRequest
        fields = (
            'public_id', 'status', 'message', 'requested_by_email', 'version_number',
            'assignments', 'created_at', 'closed_at',
        )


class ReviewCreateSerializer(serializers.Serializer):
    reviewer_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    message = serializers.CharField(required=False, allow_blank=True, default='')


@api_view(['GET', 'POST'])
@require_project_role('viewer')
def version_reviews(request, ver):
    version = request.resolved_object

    if request.method == 'GET':
        queryset = ReviewRequest.objects.filter(document_version=version).prefetch_related(
            'assignments__reviewer'
        )
        return Response({'results': ReviewRequestSerializer(queryset, many=True).data})

    if request.effective_role not in ('editor', 'admin'):
        raise Http404
    serializer = ReviewCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        review = review_service.create_review_request(
            version, request.user,
            serializer.validated_data['reviewer_ids'],
            message=serializer.validated_data['message'],
            request=request,
        )
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(ReviewRequestSerializer(review).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@require_project_role('editor')
def review_cancel(request, ver, review_id):
    version = request.resolved_object
    review = ReviewRequest.objects.filter(
        document_version=version, public_id=review_id
    ).first()
    if review is None:
        raise Http404
    try:
        review_service.cancel_review_request(review, request.user, request=request)
    except DomainError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    return Response(ReviewRequestSerializer(review).data)


@api_view(['GET'])
@require_project_role('viewer')
def version_review_context(request, ver):
    """D2: what changed (or not) since the LAST version I sealed."""
    return Response(review_service.review_context(request.resolved_object, request.user))


@api_view(['GET'])
def my_review_assignments(request):
    """The reviewer's inbox: pending work across every project (I12: only
    what my current memberships reach, including implicit org admins)."""
    org_memberships = OrganizationMembership.objects.filter(
        organization_id=OuterRef(
            'review_request__document_version__document__project__organization_id'
        ),
        user=request.user,
        is_active=True,
    )
    project_memberships = ProjectMembership.objects.filter(
        project_id=OuterRef('review_request__document_version__document__project_id'),
        user=request.user,
    )
    assignments = (
        ReviewAssignment.objects.filter(
            reviewer=request.user,
            status=ReviewAssignment.Status.PENDING,
            review_request__status=ReviewRequest.Status.OPEN,
        )
        .annotate(
            _has_org_membership=Exists(org_memberships),
            _is_org_admin=Exists(org_memberships.filter(role__in=('owner', 'admin'))),
            _has_project_membership=Exists(project_memberships),
        )
        .filter(_has_org_membership=True)
        .filter(Q(_is_org_admin=True) | Q(_has_project_membership=True))
        .select_related(
            'review_request__document_version__document__project',
            'review_request__requested_by',
        )
        .order_by('-created_at')
    )
    results = []
    for assignment in assignments:
        review = assignment.review_request
        version = review.document_version
        document = version.document
        project = document.project
        results.append({
            'review': str(review.public_id),
            'document_title': document.title,
            'version_number': version.number,
            'project_name': project.name,
            'requested_by': review.requested_by.email,
            'message': review.message,
            'scope': assignment.scope,
            'requested_at': review.created_at,
            'link': (f'/projects/{project.public_id}/documents/{document.public_id}'
                     f'/versions/{version.public_id}'),
        })
    return Response({'results': results})
