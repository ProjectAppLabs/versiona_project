"""Bounded queries for the version timeline, without loading evidence bodies."""

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from checks.models import CheckRun
from documents.models import DocumentVersion
from reviews.models import ReviewRequest, Seal


def with_document_list_data(queryset):
    """Identify each document's latest alive version without loading its history."""
    latest = DocumentVersion.objects.filter(document_id=OuterRef('pk')).order_by('-number')
    return queryset.annotate(_list_latest_version_id=Subquery(latest.values('pk')[:1]))


def prepare_document_list_versions(documents):
    """Load metadata only for the latest versions on this already-paginated page."""
    version_ids = [document._list_latest_version_id for document in documents
                   if document._list_latest_version_id is not None]
    versions = {
        version.pk: version
        for version in with_version_list_data(DocumentVersion.objects.filter(pk__in=version_ids))
    }
    for document in documents:
        document._list_latest_version = versions.get(document._list_latest_version_id)


def with_version_list_data(queryset):
    """Load timeline metadata in one query while preserving draft/check rules."""
    latest_run = CheckRun.objects.filter(
        document_version=OuterRef('pk'), status=CheckRun.Status.DONE
    ).order_by('-created_at')
    counters = {
        f'_list_check_{outcome}': Coalesce(
            Subquery(
                latest_run.annotate(
                    total=Count('results', filter=Q(results__outcome=outcome))
                ).values('total')[:1]
            ),
            0,
        )
        for outcome in ('pass', 'warn', 'fail')
    }
    return queryset.select_related('author').annotate(
        _list_has_seal=Exists(Seal.objects.filter(document_version=OuterRef('pk'))),
        _list_has_open_review=Exists(ReviewRequest.objects.filter(
            document_version=OuterRef('pk'), status=ReviewRequest.Status.OPEN
        )),
        _list_check_run_id=Subquery(latest_run.values('pk')[:1]),
        **counters,
    )
