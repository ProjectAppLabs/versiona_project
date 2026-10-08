"""Password reset commits password replacement with single-use consumption."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import (
    OperationalError,
    close_old_connections,
    connection,
    connections,
)
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import PasswordCode


@pytest.fixture
def reset_account(django_user_model):
    """Create an account with an unused password reset code."""
    user = django_user_model.objects.create_user(
        email='reset-once@versiona.test', password='Violet-River!83',
    )
    code = PasswordCode.objects.create(user=user, code='654321')
    return user, code


def reset_from_separate_connection(email, code, password, ready):
    """Submit a competing password reset from a separate database connection."""
    close_old_connections()
    try:
        client = APIClient()
        ready.wait(timeout=10)
        response = client.post(
            reverse('verify_passcode_reset'),
            {'email': email, 'code': code, 'new_password': password},
            format='json',
        )
        return response.status_code, password
    finally:
        connections.close_all()


@pytest.mark.django_db(transaction=True)
def test_concurrent_password_reset_has_one_success(reset_account):
    """Allow exactly one concurrent attempt to reset the password."""
    assert connection.vendor == 'mysql', 'This lock contract requires real MySQL.'
    user, code = reset_account
    ready = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(
                reset_from_separate_connection, user.email, code.code, password, ready,
            )
            for password in ['Amber-Cloud!74', 'Indigo-Field!62']
        ]
        outcomes = sorted(attempt.result(timeout=20) for attempt in attempts)

    assert [status for status, _ in outcomes] == [200, 400]
    user.refresh_from_db()
    code.refresh_from_db()
    assert user.check_password(outcomes[0][1]) is True
    assert user.check_password(outcomes[1][1]) is False
    assert code.used is True


@pytest.mark.django_db
@pytest.mark.parametrize('failed_row', ['password', 'code'])
def test_failed_reset_write_preserves_reusable_code(api_client, reset_account, failed_row):
    """Preserve a reusable reset code when a password reset write fails."""
    user, code = reset_account
    original_password = user.password
    tables = {'password': user._meta.db_table, 'code': code._meta.db_table}
    update_prefix = f'UPDATE {connection.ops.quote_name(tables[failed_row])}'

    def fail_after_write(execute, sql, params, many, context):
        """Raise a storage failure after SQL execution to require rollback."""
        result = execute(sql, params, many, context)
        if sql.startswith(update_prefix):
            raise OperationalError('Injected storage failure after reset write')
        return result

    payload = {
        'email': user.email, 'code': code.code, 'new_password': 'Amber-Cloud!74',
    }
    with connection.execute_wrapper(fail_after_write):
        with pytest.raises(OperationalError, match='Injected storage failure'):
            api_client.post(reverse('verify_passcode_reset'), payload, format='json')

    user.refresh_from_db()
    code.refresh_from_db()
    assert user.password == original_password
    assert code.used is False
    retried = api_client.post(reverse('verify_passcode_reset'), payload, format='json')
    assert retried.status_code == 200
    user.refresh_from_db()
    code.refresh_from_db()
    assert user.check_password('Amber-Cloud!74') is True
    assert code.used is True
