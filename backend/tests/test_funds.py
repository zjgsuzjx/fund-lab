from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import get_session
from app.main import app
from app.models import Fund, FundNav, FundRuleEvidence, Watchlist
from test_api import db


@pytest.fixture
def catalogue(db):
    now = datetime.now(timezone.utc)
    for code, name, category in [('990001', '测试债券A', '债券型-信用债'), ('990002', '测试指数C', '指数型-股票'), ('990003', '测试混合', '混合型')]:
        db.add(Fund(code=code, name=name, category=category, source_url='https://www.efunds.com.cn/', source_observed_at=now, is_sample=False, trade_enabled=False, history_complete=False))
    db.flush()
    db.add_all([FundNav(fund_code='990001', nav_date=date(2025, 9, 11), unit_nav=Decimal('1')),
                FundNav(fund_code='990001', nav_date=date(2026, 8, 11), unit_nav=Decimal('1.1')),
                FundNav(fund_code='990001', nav_date=date(2026, 9, 11), unit_nav=Decimal('1.2')),
                FundNav(fund_code='990002', nav_date=date(2026, 9, 11), unit_nav=Decimal('2'))])
    db.flush()
    app.dependency_overrides[get_session] = lambda: db
    try:
        with TestClient(app, headers={'X-Fund-Lab': '1'}) as browser:
            yield browser
    finally:
        app.dependency_overrides.clear()


def register(browser):
    response = browser.post('/api/auth/register', json={'username': 'f_' + uuid4().hex[:16], 'password': 'FundTest123'})
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
def test_combined_filter_sort_pagination(catalogue):
    client = catalogue
    result = client.get('/api/funds?q=测试&category=bond').json()
    assert [f['code'] for f in result['items']] == ['990001']
    assert result['items'][0]['year_change'] == '20.00'
    assert result['items'][0]['share_class'] == 'A'
    first = client.get('/api/funds?q=测试&sort=nav_desc&page_size=1').json()
    assert first['total'] == 3 and first['items'][0]['code'] == '990002'
    second = client.get('/api/funds?q=测试&sort=nav_desc&page_size=1&page=2').json()
    assert second['items'][0]['code'] == '990001'
    assert client.get('/api/funds?q=测试&sort=change_desc').json()['items'][-1]['code'] == '990003'
    assert client.get('/api/funds?q=测试&category=mixed').json()['items'][0]['unit_nav'] is None
    assert client.get('/api/funds?q=%25').json()['total'] == 0
    for query in ['category=invalid', 'sort=invalid', 'page=0', 'page_size=101']:
        assert client.get('/api/funds?' + query).status_code == 422
    assert client.get('/api/funds/does-not-exist').status_code == 404
    assert client.get('/api/funds/990001').headers['cache-control'] == 'no-store'


@pytest.mark.integration
def test_nav_periods_missing_data_and_rules(catalogue, db):
    client = catalogue
    series = client.get('/api/funds/990001/nav?period=1m').json()
    assert [r['date'] for r in series['items']] == ['2026-08-11', '2026-09-11']
    assert series['change'] == '9.09'
    assert '分红' in series['basis']
    all_history = client.get('/api/funds/990001/nav?period=all').json()
    assert not all_history['complete'] and all_history['change'] is None
    assert '完整' in all_history['message']
    missing = client.get('/api/funds/990003/nav').json()
    assert missing['items'] == [] and missing['change'] is None
    insufficient = client.get('/api/funds/990002/nav').json()
    assert insufficient['change'] is None and not insufficient['complete']
    assert client.get('/api/funds/990001/nav?period=5y').status_code == 422
    detail = client.get('/api/funds/990001').json()
    assert detail['rules']['minimum_purchase'] is None
    assert detail['rules']['subscription_fees'] == [] and not detail['trade_enabled']
    # Even a stray DB flag must not open the absent trading engine.
    fund = db.get(Fund, '990001'); fund.trade_enabled = True; fund.is_sample = True; db.flush()
    detail = client.get('/api/funds/990001').json()
    assert not detail['trade_enabled'] and detail['year_change'] is None
    assert client.get('/api/funds/990001/nav').json()['change'] is None


@pytest.mark.integration
def test_watchlist_idempotency_auth_and_isolation(catalogue, db):
    client = catalogue
    assert client.get('/api/funds?watchlist=true').status_code == 401
    assert client.post('/api/watchlist/990001', json={'enabled': True}).status_code == 401
    a = register(client)
    assert client.get('/api/funds?watchlist=true').json()['total'] == 0
    for _ in range(2):
        assert client.post('/api/watchlist/990001', json={'enabled': True}).status_code == 200
    assert db.scalar(select(func.count()).select_from(Watchlist).where(Watchlist.fund_code == '990001')) == 1
    assert client.get('/api/funds/990001').json()['is_watched']
    assert client.get('/api/funds?q=测试&category=bond&watchlist=true').json()['total'] == 1
    with TestClient(app, headers={'X-Fund-Lab': '1'}) as other:
        b = register(other)
        assert other.get('/api/funds?watchlist=true').json()['total'] == 0
        assert not other.get('/api/funds/990001').json()['is_watched']
        assert other.post('/api/watchlist/990001', json={'enabled': False, 'user_id': a['id']}).status_code == 422
        assert other.post('/api/watchlist/990001', json={'enabled': False}).status_code == 200
        assert client.get('/api/funds/990001').json()['is_watched']
        assert other.get('/api/funds?watchlist=true&user_id=' + a['id']).json()['total'] == 0
    assert client.post('/api/watchlist/999999', json={'enabled': True}).status_code == 404
    assert client.post('/api/watchlist/990001', json={'enabled': False}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    for _ in range(2):
        assert client.post('/api/watchlist/990001', json={'enabled': False}).status_code == 200
    assert client.get('/api/funds?watchlist=true').json()['total'] == 0
