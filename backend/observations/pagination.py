"""Fixed-size, scope-bound keyset pages for observation collections."""

from django.core import signing
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from rest_framework.exceptions import ValidationError

PAGE_SIZE = 25
CURSOR_SALT = 'observations.pages.v1'


def _position(cursor, scope):
    if cursor is None:
        return None
    try:
        payload = signing.loads(cursor, salt=CURSOR_SALT)
        if not isinstance(payload, dict) or set(payload) != {'scope', 'position'}:
            raise ValueError
        if payload['scope'] != scope or not isinstance(payload['position'], dict):
            raise ValueError
        return payload['position']
    except (signing.BadSignature, TypeError, ValueError) as exc:
        raise ValidationError({'cursor': 'El cursor no corresponde a esta consulta.'}) from exc


def _cursor(scope, position):
    return signing.dumps({'scope': scope, 'position': position}, salt=CURSOR_SALT)


def page_by_created_at(queryset, *, cursor, scope):
    """Newest first; the PK breaks timestamp ties without an offset scan."""
    position = _position(cursor, scope)
    if position is not None:
        try:
            if set(position) != {'created_at', 'pk'} or type(position['pk']) is not int:
                raise ValueError
            created_at = parse_datetime(position['created_at'])
            if not created_at or not is_aware(created_at) or position['pk'] < 1:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationError({'cursor': 'El cursor no es válido.'}) from exc
        queryset = queryset.filter(
            Q(created_at__lt=created_at)
            | Q(created_at=created_at, pk__lt=position['pk'])
        )

    rows = list(queryset.order_by('-created_at', '-pk')[:PAGE_SIZE + 1])
    page = rows[:PAGE_SIZE]
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        last = page[-1]
        next_cursor = _cursor(scope, {
            'created_at': last['created_at'].isoformat(), 'pk': last['pk'],
        })
    return page, next_cursor


def page_by_version_number(queryset, *, cursor, scope):
    """The unique anchor/version constraint makes version number sufficient."""
    position = _position(cursor, scope)
    if position is not None:
        if (
            set(position) != {'version_number'}
            or type(position['version_number']) is not int
            or position['version_number'] < 1
        ):
            raise ValidationError({'cursor': 'El cursor no es válido.'})
        queryset = queryset.filter(document_version__number__lt=position['version_number'])

    rows = list(queryset.order_by('-document_version__number')[:PAGE_SIZE + 1])
    page = rows[:PAGE_SIZE]
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        next_cursor = _cursor(scope, {
            'version_number': page[-1]['document_version__number'],
        })
    return page, next_cursor
