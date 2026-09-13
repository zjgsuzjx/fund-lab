import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db import get_engine, get_session
from app.main import app
from app.models import Fund, FundNav
from app.seed import seed


def test_liveness_does_not_require_database():
    with TestClient(app) as client:
        assert client.get('/api/health/live').json()['status'] == 'ok'


def test_database_failure_is_sanitized():
    def unavailable():
        raise OperationalError('private SQL', {}, Exception('private password'))
        yield
    app.dependency_overrides[get_session] = unavailable
    try:
        with TestClient(app) as client:
            response = client.get('/api/health/ready')
            assert response.status_code == 503
            assert 'private' not in response.text
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def db():
    # No database/table drops: every test is isolated in an outer rollback.
    with get_engine().connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            try:
                yield session
            finally:
                session.close()
                transaction.rollback()


@pytest.mark.integration
def test_seed_is_repeatable_and_preserves_existing_rows(db):
    seed(db)
    count = db.scalar(select(func.count()).select_from(Fund))
    nav_count = db.scalar(select(func.count()).select_from(FundNav))
    fund = db.get(Fund, '000147')
    fund.name = 'Preserve later edits'
    db.flush()
    seed(db)
    assert db.scalar(select(func.count()).select_from(Fund)) == count
    assert db.scalar(select(func.count()).select_from(FundNav)) == nav_count
    db.expire_all()
    assert db.get(Fund, '000147').name == 'Preserve later edits'
    assert db.get(Fund, '000147').trade_enabled is False


@pytest.mark.integration
def test_api_reads_postgres_search_and_pagination(db):
    seed(db)
    app.dependency_overrides[get_session] = lambda: db
    try:
        with TestClient(app) as client:
            assert client.get('/api/health/ready').status_code == 200
            response = client.get('/api/funds', params={'q': '000147'})
            assert response.status_code == 200
            fund = response.json()['items'][0]
            assert fund['code'] == '000147'
            assert isinstance(fund['unit_nav'], str)
            assert fund['is_sample'] is True
            assert fund['trade_enabled'] is False
            assert client.get('/api/funds', params={'q': '%'}).json()['total'] == 0
            assert len(client.get('/api/funds?page_size=2').json()['items']) == 2
            assert client.get('/api/funds?page=0').status_code == 422
            assert client.get('/api/funds?page_size=101').status_code == 422
            assert client.get('/api/funds?q=does-not-exist').json()['items'] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
def test_database_rejects_negative_nav(db):
    seed(db)
    nav = db.scalar(select(FundNav).where(FundNav.fund_code == '000147'))
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            nav.unit_nav = -1
            db.flush()
