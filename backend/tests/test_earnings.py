from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as Record

from app.earnings import profit_at
from app.models import FundNav
from test_api import db
from test_auth import client
from test_redemptions import ready_sell, NOW


def buy(day, status='confirmed'):
    return Record(trade_date=day, status=status, shares=D('100'), amount=D('101'))


def test_first_purchase_fee_and_later_nav_change():
    first, second = date(2026, 9, 17), date(2026, 9, 18)
    buys = [buy(first)]
    navs = {first: D('1'), second: D('1.1')}
    assert profit_at(first, buys, [], navs, []) == D('-1')
    assert profit_at(second, buys, [], navs, []) - profit_at(first, buys, [], navs, []) == D('10')


def test_sale_uses_historical_shares_and_net_proceeds():
    first, second = date(2026, 9, 17), date(2026, 9, 18)
    sells = [Record(trade_date=second, status='confirmed', shares=D('100'), net_amount=D('108'))]
    assert profit_at(first, [buy(first)], sells, {first: D('1')}, []) == D('-1')
    assert profit_at(second, [buy(first)], sells, {}, []) == D('7')


def test_dividend_offsets_ex_dividend_price_drop_once():
    first, second = date(2026, 9, 17), date(2026, 9, 18)
    navs = {first: D('1.1'), second: D('1')}
    dividends = [(second, D('10'))]
    assert profit_at(first, [buy(first)], [], navs, dividends) == profit_at(second, [buy(first)], [], navs, dividends)


def test_missing_nav_and_pending_trade_are_unknown_not_zero():
    day = date(2026, 9, 18)
    assert profit_at(day, [buy(day)], [], {}, []) is None
    assert profit_at(day, [buy(day, 'pending')], [], {day: D('1')}, []) is None
    assert profit_at(day, [buy(day, 'cancelled')], [], {}, []) == 0


def test_holdings_api_earnings_date_and_values(ready_sell):
    client, db, clock, account, lots = ready_sell
    db.add(FundNav(fund_code='000147', nav_date=NOW.date(), unit_nav=D('1.20')))
    db.commit()
    result = client.get('/api/holdings').json()
    assert result['earnings_date'] == '2026-09-17'
    assert result['latest_profit'] == '20.00'
    assert result['items'][0]['latest_profit'] == '20.00'
    assert result['holding_return'] == '19.05'
    assert result['earnings_history'][0] == {'date': '2026-09-17', 'profit': '20.00'}
    assert result['earnings_history'][1]['profit'] is None  # Missing 09-15 NAV.
