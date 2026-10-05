"""Project observation summaries and content fragments inside the database.

Read paths never materialize complete bodies, reply arrays or JSON coordinates.
Mutation services keep their existing state machine and return these same summaries.
"""

from django.db.models import Count, Func, OuterRef, Subquery, TextField
from django.db.models.functions import Coalesce, Length, Substr

from .models import Observation, ObservationAnchor, ObservationReply

BODY_PREVIEW_SIZE = 500
CONTENT_CHUNK_SIZE = 8192


class JsonText(Func):
    """JSON text with a character-count contract matching the chunk query."""

    template = 'CAST(%(expressions)s AS TEXT)'
    output_field = TextField()

    def as_mysql(self, compiler, connection, **extra_context):
        return self.as_sql(
            compiler, connection,
            template='CAST(%(expressions)s AS CHAR CHARACTER SET utf8mb4)',
            **extra_context,
        )


def observation_rows(queryset=None, *, version_id=None):
    queryset = queryset if queryset is not None else Observation.objects.all()
    replies = (
        ObservationReply.objects.filter(observation_id=OuterRef('pk'))
        .order_by().values('observation_id').annotate(total=Count('pk'))
    )
    annotations = {
        'body_preview': Substr('body', 1, BODY_PREVIEW_SIZE),
        'body_length': Length('body'),
        'reply_count': Coalesce(Subquery(replies.values('total')[:1]), 0),
    }
    if version_id is not None:
        anchor = ObservationAnchor.objects.filter(
            observation_id=OuterRef('pk'), document_version__public_id=version_id,
        )
        annotations.update({
            '_anchor_number': Subquery(anchor.values('document_version__number')[:1]),
            '_anchor_public_id': Subquery(anchor.values('document_version__public_id')[:1]),
            '_anchor_deleted_at': Subquery(anchor.values('document_version__deleted_at')[:1]),
            '_anchor_page': Subquery(anchor.values('page')[:1]),
            '_anchor_method': Subquery(anchor.values('method')[:1]),
            '_anchor_snippet': Subquery(
                anchor.annotate(snippet=Substr('text_snippet', 1, 300)).values('snippet')[:1]
            ),
            '_anchor_quads_length': Subquery(
                anchor.annotate(length=Length(JsonText('quads'))).values('length')[:1]
            ),
        })
    return queryset.annotate(**annotations).values(
        'pk', 'public_id', 'status', 'author__email', 'section__stable_key',
        'section__title_current', 'created_on_version__number',
        'resolved_in_version__number', 'created_at', *annotations,
    )


def reply_rows(queryset):
    return queryset.annotate(
        body_preview=Substr('body', 1, BODY_PREVIEW_SIZE), body_length=Length('body'),
    ).values(
        'pk', 'public_id', 'author__email', 'status_change', 'created_at',
        'body_preview', 'body_length',
    )


def anchor_rows(queryset):
    return queryset.annotate(
        snippet=Substr('text_snippet', 1, 300), quads_length=Length(JsonText('quads')),
    ).values(
        'observation_id', 'document_version__number', 'document_version__public_id',
        'document_version__deleted_at', 'page', 'method',
        'snippet', 'quads_length',
    )


def anchor_summary(row, observation_id):
    version_number = row['document_version__number']
    return {
        'version_number': version_number,
        'version_public_id': str(row['document_version__public_id']),
        'version_is_trashed': row['document_version__deleted_at'] is not None,
        'page': row['page'],
        'method': row['method'],
        'text_snippet': row['snippet'],
        'quads_length': row['quads_length'],
        'quads_content_url': (
            f'/api/observations/{observation_id}/anchors/{version_number}/content/'
        ),
    }


def observation_summary(row, *, current_anchor=None):
    public_id = str(row['public_id'])
    if row.get('_anchor_number') is not None:
        current_anchor = anchor_summary({
            'document_version__number': row['_anchor_number'],
            'document_version__public_id': row['_anchor_public_id'],
            'document_version__deleted_at': row['_anchor_deleted_at'],
            'page': row['_anchor_page'],
            'method': row['_anchor_method'],
            'snippet': row['_anchor_snippet'],
            'quads_length': row['_anchor_quads_length'],
        }, public_id)
    return {
        'public_id': public_id,
        'body_preview': row['body_preview'],
        'body_length': row['body_length'],
        'body_content_url': f'/api/observations/{public_id}/content/',
        'status': row['status'],
        'author_email': row['author__email'],
        'section_key': row['section__stable_key'],
        'section_heading': row['section__title_current'],
        'created_on': row['created_on_version__number'],
        'resolved_in': row['resolved_in_version__number'],
        'created_at': row['created_at'],
        'reply_count': row['reply_count'],
        'current_anchor': current_anchor,
    }


def reply_summary(row, observation_id):
    public_id = str(row['public_id'])
    return {
        'public_id': public_id,
        'body_preview': row['body_preview'],
        'body_length': row['body_length'],
        'body_content_url': (
            f'/api/observations/{observation_id}/replies/{public_id}/content/'
        ),
        'author_email': row['author__email'],
        'status_change': row['status_change'],
        'created_at': row['created_at'],
    }


def content_fragment(queryset, expression, offset):
    """Return only length and one Unicode fragment, never the original field."""
    fragments = queryset.order_by().annotate(
        content_length=Length(expression),
        content_piece=Substr(expression, offset + 1, CONTENT_CHUNK_SIZE),
    ).values('content_length', 'content_piece')[:1]
    # Every caller scopes one unique child. first() would reintroduce PK
    # ordering and force MySQL to sort a large JSON source unnecessarily.
    return next(iter(fragments), None)
