from decimal import Decimal

import pytest
from sqlalchemy import select, func

from app.models import BuyOrder, CashLedger, PositionLot, SellOrder, Watchlist, Fund
from test_api import db
from test_auth import client, credentials
from test_redemptions import ready_sell, request_body


@pytest.mark.integration
def test_reset_populated_account(ready_sell):
    client, db, clock, account, lots = ready_sell
    body, _ = request_body(client)
    client.post('/api/redemptions', json=body).raise_for_status()
    db.add(Watchlist(user_id=account.user_id, fund_code='000147'))
    db.commit()
    original = account.available_cash
    assert client.post('/api/account/reset', json={'current_password': 'wrong'}).status_code == 400
    db.refresh(account)
    assert account.available_cash == original
    assert db.scalar(select(func.count()).select_from(PositionLot).where(PositionLot.account_id == account.id)) == 2
    assert client.post('/api/account/reset', json={'current_password': 'StrongPass123'}).status_code == 204
    db.refresh(account)
    assert (account.available_cash, account.reserved_cash, account.redemption_cash) == (Decimal('100000'), 0, 0)
    for model in (BuyOrder, SellOrder, PositionLot):
        assert db.scalar(select(func.count()).select_from(model).where(model.account_id == account.id)) == 0
    assert db.get(Watchlist, (account.user_id, '000147')) is None
    assert db.get(Fund, '000147') is not None
    entries = db.scalars(select(CashLedger).where(CashLedger.account_id == account.id)).all()
    assert len(entries) == 1 and entries[0].kind == 'initial_capital'
    assert client.get('/api/account').status_code == 401


@pytest.mark.integration
def test_reset_isolation_and_login(client, db):
    a, b = credentials(), credentials()
    client.post('/api/auth/register', json=a).raise_for_status()
    first = client.get('/api/account').json()
    client.post('/api/auth/register', json=b).raise_for_status()
    second = client.get('/api/account').json()
    assert client.post('/api/account/reset', json={'current_password': b['password'], 'account_id': first['id']}).status_code == 422
    assert client.post('/api/account/reset', json={'current_password': b['password']}).status_code == 204
    assert client.post('/api/auth/login', json=b).status_code == 200
    assert client.get('/api/account').json()['id'] == second['id']
    assert client.post('/api/auth/login', json=a).status_code == 200
    assert client.get('/api/account').json() == first


@pytest.mark.integration
def test_reset_requires_session_and_write_guard(client):
    assert client.post('/api/account/reset', json={'current_password': 'StrongPass123'}).status_code == 401
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    assert client.post('/api/account/reset', json={'current_password': 'StrongPass123'}, headers={'X-Fund-Lab': '0'}).status_code == 403
