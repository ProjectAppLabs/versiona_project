"""Project report projections without materializing document histories."""

from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from checks.models import CheckRun
from documents.models import Document, DocumentVersion
from observations.models import Observation
from reviews.models import Seal
from reviews.services.seal_service import valid_seals_at_number


def _report_documents(project):
    latest_version = DocumentVersion.objects.filter(
        document_id=OuterRef('pk')
    ).order_by('-number')
    open_observations = (
        Observation.objects.filter(document_id=OuterRef('pk'), status=Observation.Status.OPEN)
        .order_by()
        .values('document_id')
        .annotate(total=Count('pk'))
        .values('total')
    )
    latest_run = CheckRun.objects.filter(
        document_version_id=OuterRef('_report_version_id'), status=CheckRun.Status.DONE
    ).order_by('-created_at')
    check_counters = {
        f'_report_check_{outcome}': Coalesce(
            Subquery(
                latest_run.annotate(
                    total=Count('results', filter=Q(results__outcome=outcome))
                ).values('total')[:1]
            ),
            0,
        )
        for outcome in ('pass', 'warn', 'fail')
    }
    return (
        Document.objects.filter(project=project)
        .annotate(
            _report_version_id=Subquery(latest_version.values('pk')[:1]),
            _report_version_number=Subquery(latest_version.values('number')[:1]),
            _report_approved=Subquery(latest_version.values('is_approved')[:1]),
        )
        .filter(_report_version_id__isnull=False)
        .annotate(
            _report_open_observations=Coalesce(Subquery(open_observations), 0),
            _report_check_run_id=Subquery(latest_run.values('pk')[:1]),
            **check_counters,
        )
        .values(
            'pk', 'title', '_report_version_number', '_report_approved',
            '_report_open_observations', '_report_check_run_id',
            '_report_check_pass', '_report_check_warn', '_report_check_fail',
        )
    )


def _valid_seal_counts(project):
    latest_version = DocumentVersion.objects.filter(
        document_id=OuterRef('document_version__document_id')
    ).order_by('-number')
    seals = valid_seals_at_number(
        Seal.objects.filter(
            document_version__document__project=project,
            document_version__document__deleted_at__isnull=True,
        ),
        Subquery(latest_version.values('number')[:1]),
    )
    return dict(
        seals.order_by()
        .values('document_version__document_id')
        .annotate(total=Count('pk'))
        .values_list('document_version__document_id', 'total')
    )


def project_report_documents(project) -> list[dict]:
    """Keep the report contract with one metadata query and one seal aggregate."""
    seal_counts = _valid_seal_counts(project)
    return [
        {
            'document': document['title'],
            'latest_version': document['_report_version_number'],
            'approved': document['_report_approved'],
            'valid_seals': seal_counts.get(document['pk'], 0),
            'open_observations': document['_report_open_observations'],
            'checks': (
                {
                    outcome: document[f'_report_check_{outcome}']
                    for outcome in ('pass', 'warn', 'fail')
                }
                if document['_report_check_run_id'] is not None else None
            ),
        }
        for document in _report_documents(project).iterator(chunk_size=500)
    ]
