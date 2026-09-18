from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.auth import COOKIE, password_hash, token_digest, verify_password
from app.db import get_session
from app.main import app
from app.models import AuthSession, CashLedger, SimulationAccount, User
from test_api import db

from app.throttle import _buckets

HEADERS = {'X-Fund-Lab': '1'}


@pytest.fixture
def client(db):
    app.dependency_overrides[get_session] = lambda: db
    try:
        with TestClient(app, headers=HEADERS) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def credentials():
    return {'username': 'u_' + uuid4().hex[:16], 'password': 'StrongPass123'}


def test_password_hash_is_salted_and_verifiable():
    a, b = password_hash('StrongPass123'), password_hash('StrongPass123')
    assert a != b and 'StrongPass' not in a
    assert verify_password('StrongPass123', a)
    assert not verify_password('wrong', a)
    assert not verify_password('wrong', 'invalid')


@pytest.mark.integration
def test_register_login_refresh_logout_and_one_grant(client, db):
    body = credentials()
    response = client.post('/api/auth/register', json=body)
    assert response.status_code == 201
    assert 'password' not in response.text
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    assert response.headers['cache-control'] == 'no-store'
    token = client.cookies.get(COOKIE)
    assert db.get(AuthSession, token_digest(token)) is not None
    assert db.get(AuthSession, token) is None
    user = client.get('/api/auth/me').json()
    assert user['username'] == body['username']
    account = client.get('/api/account').json()
    assert account['available_cash'] == '100000.00'
    entries = client.get('/api/account/ledger').json()['items']
    assert len(entries) == 1 and entries[0]['amount'] == '100000.00'
    duplicate = {**body, 'username': body['username'].upper()}
    assert client.post('/api/auth/register', json=duplicate).status_code == 409
    assert client.get('/api/account').json() == account
    assert len(client.get('/api/account/ledger').json()['items']) == 1
    # A new browser request with the cookie restores the same identity.
    with TestClient(app) as refreshed:
        refreshed.cookies.set(COOKIE, token)
        assert refreshed.get('/api/auth/me').json() == user
    assert client.post('/api/auth/logout', json={}).status_code == 204
    assert client.get('/api/account').status_code == 401
    assert db.get(AuthSession, token_digest(token)) is None
    with TestClient(app) as attacker:
        attacker.cookies.set(COOKIE, token)
        assert attacker.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/logout', json={}).status_code == 204
    assert client.post('/api/auth/login', json={**body, 'password': 'wrong'}).status_code == 401
    login = client.post('/api/auth/login', json={**body, 'remember': True})
    assert login.status_code == 200 and 'Max-Age=2592000' in login.headers['set-cookie']
    assert len(client.get('/api/account/ledger').json()['items']) == 1
    row = db.get(AuthSession, token_digest(client.cookies.get(COOKIE)))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()
    assert client.get('/api/account').status_code == 401


@pytest.mark.integration
def test_user_isolation_and_password_change(client, db):
    a, b = credentials(), credentials()
    assert client.post('/api/auth/register', json=a).status_code == 201
    a_token = client.cookies.get(COOKIE)
    a_user = client.get('/api/auth/me').json()
    a_account = client.get('/api/account').json()
    with TestClient(app, headers=HEADERS) as other:
        assert other.post('/api/auth/register', json=b).status_code == 201
        b_token = other.cookies.get(COOKIE)
        b_user = other.get('/api/auth/me').json()
        b_account = other.get('/api/account').json()
        b_ledger = other.get('/api/account/ledger').json()
        assert a_account['id'] != b_account['id']
        assert client.get('/api/account', params={'user_id': b_user['id'], 'account_id': b_account['id']}).json() == a_account
        assert client.get('/api/account/ledger', params={'account_id': b_account['id']}).json() != b_ledger
        assert client.get(f"/api/accounts/{b_account['id']}").status_code == 404
        assert client.patch('/api/account', json={'id': b_account['id'], 'available_cash': '999999'}).status_code == 405
        assert client.post('/api/account/password', json={'current_password': a['password'], 'new_password': 'ChangedPass123', 'user_id': b_user['id']}).status_code == 422
        assert other.get('/api/account').json() == b_account
        assert client.post('/api/account/password', json={'current_password': 'wrong', 'new_password': 'ChangedPass123'}).status_code == 400
        # A second valid A session must also be revoked after password change.
        with TestClient(app, headers=HEADERS) as second:
            assert second.post('/api/auth/login', json=a).status_code == 200
            assert client.post('/api/account/password', json={'current_password': a['password'], 'new_password': 'ChangedPass123'}).status_code == 204
            assert second.get('/api/account').status_code == 401
        assert client.get('/api/account').status_code == 401
        assert db.get(AuthSession, token_digest(a_token)) is None
        assert db.get(AuthSession, token_digest(b_token)) is not None
        assert other.get('/api/auth/me').json() == b_user
        assert client.post('/api/auth/login', json=a).status_code == 401
        assert client.post('/api/auth/login', json={**a, 'password': 'ChangedPass123'}).status_code == 200
        assert client.get('/api/auth/me').json() == a_user
        assert other.get('/api/account/ledger').json() == b_ledger


@pytest.mark.integration
def test_validation_csrf_and_atomic_rollback(client, db):
    body = credentials()
    with TestClient(app) as cross_site:
        assert cross_site.post('/api/auth/register', json=body).status_code == 403
    assert client.post('/api/auth/register', json=body, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    for invalid in [{'username': 'a'}, {'username': 'bad name'}, {'password': '12345678'}, {'password': 'abcdefgh'}, {'password': 'a' * 129}, {'user_id': str(uuid4())}]:
        assert client.post('/api/auth/register', json={**body, **invalid}).status_code == 422
    assert db.scalar(select(User).where(User.username == body['username'])) is None
    # Failure before commit must not leave a user, cash balance or grant behind.
    with patch.object(db, 'commit', side_effect=OperationalError('private', {}, Exception('secret'))):
        response = client.post('/api/auth/register', json=body)
        assert response.status_code == 503 and 'secret' not in response.text
    db.rollback()
    assert db.scalar(select(User).where(User.username == body['username'])) is None
    assert client.post('/api/auth/register', json=body).status_code == 201
    account = db.scalar(select(SimulationAccount).join(User).where(User.username == body['username']))
    assert account.available_cash == Decimal('100000.00')
    assert db.scalar(select(func.count()).select_from(CashLedger).where(CashLedger.account_id == account.id)) == 1


@pytest.mark.integration
def test_concurrent_registration_has_exactly_one_grant():
    """Use independent real transactions; delete only this test's generated user."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import delete
    from sqlalchemy.orm import Session
    from app.db import get_engine
    body = credentials()
    barrier = Barrier(2)

    def request():
        with TestClient(app, headers=HEADERS) as browser:
            barrier.wait(timeout=10)
            return browser.post('/api/auth/register', json=body).status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: request(), range(2)))
        assert sorted(results) == [201, 409]
        with Session(get_engine()) as session:
            user = session.scalar(select(User).where(User.username == body['username']))
            accounts = session.scalars(select(SimulationAccount).where(SimulationAccount.user_id == user.id)).all()
            assert len(accounts) == 1 and accounts[0].available_cash == Decimal('100000.00')
            entries = session.scalars(select(CashLedger).where(CashLedger.account_id == accounts[0].id)).all()
            assert len(entries) == 1 and entries[0].amount == Decimal('100000.00')
    finally:
        with Session(get_engine()) as session:
            user = session.scalar(select(User).where(User.username == body['username']))
            if user:
                account_ids = select(SimulationAccount.id).where(SimulationAccount.user_id == user.id)
                session.execute(delete(CashLedger).where(CashLedger.account_id.in_(account_ids)))
                session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
                session.execute(delete(SimulationAccount).where(SimulationAccount.user_id == user.id))
                session.delete(user)
                session.commit()



def test_auth_rate_limit():
    from starlette.requests import Request
    from fastapi import HTTPException
    from app.throttle import throttle
    request = Request({'type': 'http', 'client': ('rate-test', 1234)})
    for _ in range(30):
        throttle(request)
    with pytest.raises(HTTPException) as rejected:
        throttle(request)
    assert rejected.value.status_code == 429
    assert rejected.value.headers['Retry-After'] == '60'
