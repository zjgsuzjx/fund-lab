"""Economic-date earnings reconstructed from confirmed trades, not today's lots."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from .models import BuyOrder, SellOrder, FundNav, DividendPayment, DividendEvent
from .trade_rules import rounded, trading_day


def profit_at(day, buys, sells, navs, dividends):
    shares, invested, proceeds = Decimal(0), Decimal(0), Decimal(0)
    for buy in buys:
        if buy.trade_date <= day and buy.status != 'cancelled':
            if buy.status != 'confirmed':
                return None
            shares += buy.shares
            invested += buy.amount
    for sell in sells:
        if sell.trade_date <= day and sell.status != 'cancelled':
            if sell.status not in ('confirmed', 'paid'):
                return None
            shares -= sell.shares
            proceeds += sell.net_amount
    if shares < 0 or (shares and day not in navs):
        return None
    value = rounded(shares * navs[day]) if shares else Decimal(0)
    income = sum((amount for ex_date, amount in dividends if ex_date <= day), Decimal(0))
    return value + proceeds + income - invested


def earnings(db, account_id, today, warning=''):
    buys = db.scalars(select(BuyOrder).where(BuyOrder.account_id == account_id, BuyOrder.status != 'cancelled')).all()
    sells = db.scalars(select(SellOrder).where(SellOrder.account_id == account_id, SellOrder.status != 'cancelled')).all()
    codes = sorted({b.fund_code for b in buys})
    nav_rows = db.scalars(select(FundNav).where(FundNav.fund_code.in_(codes), FundNav.nav_date <= today)).all() if codes else []
    navs = {code: {n.nav_date: n.unit_nav for n in nav_rows if n.fund_code == code} for code in codes}
    latest = max((n.nav_date for n in nav_rows), default=None)
    payments = db.execute(select(DividendPayment, DividendEvent).join(DividendEvent).where(DividendPayment.account_id == account_id)).all()
    series, by_fund = [], {}
    if latest and latest.year == 2026:
        for offset in range(29, -1, -1):
            day = latest - timedelta(days=offset)
            if day.year != 2026 or not trading_day(day):
                continue
            previous = day - timedelta(days=1)
            while previous.year == 2026 and not trading_day(previous):
                previous -= timedelta(days=1)
            daily = {}
            for code in codes:
                cb = [b for b in buys if b.fund_code == code]
                cs = [s for s in sells if s.fund_code == code]
                dividends = [(e.ex_date, p.amount) for p, e in payments if e.fund_code == code and e.ex_date]
                current = profit_at(day, cb, cs, navs[code], dividends)
                before = profit_at(previous, cb, cs, navs[code], dividends)
                daily[code] = rounded(current - before) if current is not None and before is not None and not warning else None
            value = sum(daily.values(), Decimal(0)) if all(v is not None for v in daily.values()) else None
            # Do not invent earnings history before the first investment.
            if any(b.trade_date <= day for b in buys):
                series.append({'date': day, 'profit': str(value) if value is not None else None})
            if day == latest:
                by_fund = {code: str(value) if value is not None else None for code, value in daily.items()}
    return {'earnings_date': latest, 'latest_profit': series[-1]['profit'] if series and series[-1]['date'] == latest else None,
            'earnings_history': list(reversed(series)), 'fund_latest_profit': by_fund,
            'earnings_note': warning or '按交易计价日还原每日份额，收益包含申赎费用及已登记现金分红；缺少净值或交易尚未确认时待更新。'}
