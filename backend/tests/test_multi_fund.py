import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models import Fund, FundNav, FundSyncRun, DataUpdateJob, Watchlist, PositionLot
from app.trade_rules import CN, RULE, fees, rule_for, schedule, trading_day
from app.trading_calendar import parse_calendar
from app.sync_funds import fetch_bundle, synchronize, sync_directory
from app.maintenance import due_codes, request_update, run_update, scheduled_slot
from app.trades import settle_buy
from app.redemptions import settle_sell
from test_api import db
from test_auth import client, credentials
from test_trades import ready, NOW


def test_per_fund_profiles_are_independent_and_unsupported_products_fail_closed():
    a = SimpleNamespace(code='000001', name='普通股票A', category='股票型')
    b = SimpleNamespace(code='000002', name='普通债券C', category='债券型')
    first, second = rule_for(a), rule_for(b)
    assert first['version'] != second['version']
    assert fees(Decimal('1000'), first)[:2] == (Decimal('0.00'), Decimal('1000.00'))
    first['fee_tiers'][0]['rate'] = '0.9'
    assert rule_for(a)['fee_tiers'][0]['rate'] == second['fee_tiers'][0]['rate'] == '0'
    for name, category in [('海外QDII', 'QDII'), ('现金宝', '货币型'), ('三年持有混合', '混合型'), ('沪深ETF', '指数型')]:
        assert rule_for(SimpleNamespace(code='123456', name=name, category=category)) is None


def test_cross_year_and_calendar_import(tmp_path, monkeypatch):
    import app.trading_calendar as calendar
    monkeypatch.setattr(calendar, 'CACHE', tmp_path)
    trade, confirm, _ = schedule(datetime(2025, 12, 31, 14, tzinfo=CN))
    assert (trade, confirm) == (date(2025, 12, 31), date(2026, 1, 5))
    assert not trading_day(date(2025, 2, 8))  # Makeup working Saturday stays closed.
    with pytest.raises(HTTPException):
        schedule(datetime(2026, 12, 31, 14, tzinfo=CN))
    # Synthetic future fixture verifies loading, not an assertion of 2027 real holidays.
    ranges = [[a.replace('2026', '2027'), b.replace('2026', '2027')] for a, b in calendar.BUILTIN[2026]]
    (tmp_path / '2027.json').write_text(json.dumps({'year': 2027, 'ranges': ranges, 'source': calendar.SOURCE}))
    assert schedule(datetime(2026, 12, 31, 14, tzinfo=CN))[1] == date(2027, 1, 4)
    (tmp_path / '2027.json').write_text('{}')
    with pytest.raises(HTTPException):
        trading_day(date(2027, 1, 4))


def test_annual_calendar_parser_rejects_partial_publications():
    body = '2026年休市安排 元旦：1月1日（星期四）至1月3日（星期六）休市。春节：2月15日（星期日）至2月23日（星期一）休市。清明节：4月4日（星期六）至4月6日（星期一）休市。劳动节：5月1日（星期五）至5月5日（星期二）休市。端午节：6月19日（星期五）至6月21日（星期日）休市。中秋节：9月25日（星期五）至9月27日（星期日）休市。国庆节：10月1日（星期四）至10月7日（星期三）休市。相关公告'
    assert len(parse_calendar(body)[1]) == 7
    with pytest.raises(ValueError):
        parse_calendar(body.replace('春节', '未知'))


class MarketTransport:
    def __init__(self, run_id=None):
        self.evidence = []

    def get(self, url):
        self.evidence.append({'url': url})
        if 'fundcode_search' in url:
            return 'var r = ' + json.dumps([['991001', 'x', '跨公司测试股票A', '股票型', 'x'], ['991002', 'x', '跨公司测试债券C', '债券型', 'x']]) + ';'
        assert 'efunds' not in url
        return json.dumps({'TotalCount': 2, 'Data': {'LSJZList': [
            {'FSRQ': '2026-09-14', 'DWJZ': '1.1', 'LJJZ': '1.2'},
            {'FSRQ': '2026-09-11', 'DWJZ': '1.0', 'LJJZ': '1.1'}]}})


def test_full_directory_import_and_generic_nav_sync(db):
    assert sync_directory(db, MarketTransport()) == 2
    fund = db.get(Fund, '991001')
    assert not fund.trade_enabled and fund.is_sample
    assert synchronize(db, fund.code, transport_factory=MarketTransport)['status'] == 'success'
    assert fund.trade_enabled and not fund.is_sample
    assert db.get(FundNav, (fund.code, date(2026, 9, 14))).unit_nav == Decimal('1.1')
    sync_directory(db, MarketTransport())
    assert fund.trade_enabled and fund.last_sync_at is not None
    assert synchronize(db, fund.code, transport_factory=MarketTransport)['inserted'] == 0


def test_multi_fund_buy_sell_accounting_and_snapshot_isolation(ready):
    client, db, clock = ready
    for code in ('991001', '991002'):
        db.add(Fund(code=code, name=f'多基金测试{code}A', category='股票型', source_url='https://example.invalid',
                    source_observed_at=NOW, last_sync_at=NOW, is_sample=False, trade_enabled=True))
    db.flush()
    buys = []
    for code, amount, nav in [('991001', '1000', '1'), ('991002', '2000', '2')]:
        q = client.post('/api/trades/quote', json={'fund_code': code, 'amount': amount}).json()
        assert q['fee'] == '0.00' and q['rule']['fund_code'] == code
        payload = {'fund_code': code, 'amount': amount, 'request_key': str(uuid4()), 'rule_version': q['rule_version'], 'trade_date': q['trade_date']}
        assert client.post('/api/orders', json={**payload, 'rule_version': RULE['version']}).status_code == 409
        response = client.post('/api/orders', json=payload)
        response.raise_for_status()
        buys.append(response.json())
        db.add(FundNav(fund_code=code, nav_date=NOW.date(), unit_nav=Decimal(nav)))
    db.flush()
    aid = UUID(client.get('/api/account').json()['id'])
    for order in buys:
        settle_buy(db, aid, UUID(order['id']), lambda: NOW + timedelta(days=1))
    db.commit()
    clock[0] = NOW + timedelta(days=2)
    holdings = client.get('/api/holdings').json()
    assert len(holdings['items']) == 2 and holdings['total_assets'] == '100000.00'
    q = client.post('/api/redemptions/quote', json={'fund_code': '991001', 'shares': '100'}).json()
    assert q['rule']['fund_code'] == '991001' and q['fee'] == '1.50'
    response = client.post('/api/redemptions', json={'fund_code': '991001', 'shares': '100', 'request_key': str(uuid4()), 'quote_token': q['quote_token']})
    response.raise_for_status()
    sold = response.json()
    db.add(FundNav(fund_code='991001', nav_date=clock[0].date(), unit_nav=Decimal('1.2')))
    db.flush()
    settle_sell(db, aid, UUID(sold['id']), lambda: NOW + timedelta(days=20))
    db.commit()
    assert db.scalar(select(PositionLot.remaining_shares).where(PositionLot.account_id == aid, PositionLot.fund_code == '991002')) == 1000
    detail = client.get(f"/api/redemptions/{sold['id']}")
    assert detail.json()['status'] == 'paid' and detail.json()['net_amount'] == '118.20'
    assert client.get('/api/account').json()['available_cash'] == '97118.20'


def test_scheduled_priority_retry_and_per_fund_manual_updates(db):
    # Isolate the scheduler's candidate set inside the outer rollback.
    db.execute(delete(DataUpdateJob))
    for fund in db.scalars(select(Fund)):
        fund.last_sync_at = NOW
    sync_directory(db, MarketTransport())
    fund = db.get(Fund, '991002')
    fund.last_sync_at = None
    request_update(db, NOW, '991002')
    db.flush()
    assert due_codes(db, NOW, 1) == ['991002']
    calls = []
    def sync(session, code):
        calls.append(code)
        return {'status': 'failed'}
    run_update(db, NOW, sync, code='991002', scheduled=True)
    assert '991002' not in due_codes(db, NOW + timedelta(minutes=14))
    assert '991002' in due_codes(db, NOW + timedelta(minutes=15))
    assert calls == ['991002']
    assert scheduled_slot(datetime(2026, 9, 20, 7, tzinfo=CN)) == datetime(2026, 9, 19, 23, tzinfo=CN)
    assert scheduled_slot(datetime(2026, 9, 20, 20, tzinfo=CN)).hour == 20
