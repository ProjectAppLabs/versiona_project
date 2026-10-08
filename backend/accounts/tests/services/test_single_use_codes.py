"""Backup codes are consumed from the current row, including concurrent calls."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from django.db import close_old_connections, connection, connections

from accounts import twofactor


@pytest.fixture
def enrolled_user(django_user_model):
    """Enroll an account with TOTP and fresh backup codes."""
    user = django_user_model.objects.create_user(
        email='backup-once@versiona.test', password='Violet-River!83',
    )
    enrollment = twofactor.setup(user)
    codes = twofactor.enable(user, pyotp.TOTP(enrollment['secret']).now())
    return user, codes


def consume_from_separate_connection(user_model, user_id, code, ready):
    """Both callers hold their own pre-consumption instance before competing."""
    close_old_connections()
    try:
        user = user_model.objects.get(pk=user_id)
        ready.wait(timeout=10)
        return twofactor.verify_code(user, code)
    finally:
        connections.close_all()


@pytest.mark.django_db
def test_backup_code_rejects_reuse_from_a_stale_user(enrolled_user):
    """Reject a consumed backup code from a stale user instance."""
    user, codes = enrolled_user
    stale_user = type(user).objects.get(pk=user.pk)

    first = twofactor.verify_code(user, codes[0])
    reused = twofactor.verify_code(stale_user, codes[0])

    assert first is True
    assert reused is False
    user.refresh_from_db()
    assert len(user.totp_backup_codes) == twofactor.BACKUP_CODE_COUNT - 1


@pytest.mark.django_db
def test_distinct_backup_codes_preserve_previous_consumption(enrolled_user):
    """Preserve previous consumption when a stale user uses another code."""
    user, codes = enrolled_user
    stale_user = type(user).objects.get(pk=user.pk)
    remaining = user.totp_backup_codes[2:]

    first = twofactor.verify_code(user, codes[0])
    second = twofactor.verify_code(stale_user, codes[1])

    assert first is True
    assert second is True
    user.refresh_from_db()
    assert user.totp_backup_codes == remaining


@pytest.mark.django_db
def test_invalid_backup_code_preserves_available_codes(enrolled_user):
    """Preserve available backup codes when verification rejects a code."""
    user, _ = enrolled_user
    available = list(user.totp_backup_codes)

    accepted = twofactor.verify_code(user, 'not-a-backup-code')

    assert accepted is False
    user.refresh_from_db()
    assert user.totp_backup_codes == available


@pytest.mark.django_db(transaction=True)
def test_concurrent_backup_code_has_one_success(enrolled_user):
    """Allow exactly one concurrent attempt to consume a backup code."""
    assert connection.vendor == 'mysql', 'This lock contract requires real MySQL.'
    user, codes = enrolled_user
    remaining = user.totp_backup_codes[1:]
    ready = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(
                consume_from_separate_connection, type(user), user.pk, codes[0], ready,
            )
            for _ in range(2)
        ]
        outcomes = [attempt.result(timeout=20) for attempt in attempts]

    assert sorted(outcomes) == [False, True]
    user.refresh_from_db()
    assert user.totp_backup_codes == remaining
