"""Opt-in integration tests against a dedicated disposable PostgreSQL database."""
import os
from datetime import date
import pytest
from rackpulse.repository import Repository


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='dedicated PostgreSQL TEST_DATABASE_URL not configured')
def test_postgres_lock_and_migrations():
    from alembic import command
    from alembic.config import Config
    url = os.environ['TEST_DATABASE_URL']
    assert url.startswith('postgresql'), 'integration tests require PostgreSQL'
    original = os.environ.get('DATABASE_URL')
    try:
        os.environ['DATABASE_URL'] = url
        command.upgrade(Config('alembic.ini'), 'head')
    finally:
        if original is None:
            os.environ.pop('DATABASE_URL', None)
        else:
            os.environ['DATABASE_URL'] = original
    first, second = Repository(url), Repository(url)
    with first.acquire_day(date(2099, 1, 1)):
        with pytest.raises(ValueError, match='day_already_running'):
            with second.acquire_day(date(2099, 1, 1)):
                pass
