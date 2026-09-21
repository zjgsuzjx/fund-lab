"""Audited cash-only simulation distributions; never infer an ex-date from a NAV drop."""
import argparse
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import CurrentUser, DB, owned_account
from .models import BuyOrder, CashLedger, DividendEvent, DividendPayment, FundNav, PositionLot, SellAllocation, SellOrder
from .trade_rules import CN, rounded, utcnow

router = APIRouter(prefix='/api')
POLICY = 'cash-simulation-v1'
POLICY_NOTE = '现金分红模拟：登记日申购不参与、登记日赎回仍参与；按账户合计份额四舍五入到分。小额红利仍发现金，不模拟自动转投；公告发放日作为模拟到账日。'


def cash_note_matches(note, amount):
    match = re.fullmatch(r'每份(?:派现金|分红)([0-9]+(?:\.[0-9]+)?)元', (note or '').strip())
    return bool(match and Decimal(match[1]) == amount)


class ReviewedDividend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fund_code: str = Field(pattern=r'^[0-9]{6}$')
    record_date: date
    ex_date: date
    pay_date: date
    cash_per_share: Decimal = Field(gt=0, lt=1000, decimal_places=8, allow_inf_nan=False)
    source_url: HttpUrl
    source_excerpt: str = Field(min_length=10, max_length=2000)
    policy: Literal['cash-simulation-v1']

    @model_validator(mode='after')
    def dates(self):
        if not self.record_date <= self.ex_date <= self.pay_date:
            raise ValueError('登记日、除息日、发放日顺序错误。')
        if len(str(self.source_url)) > 1000 or self.source_url.scheme != 'https':
            raise ValueError('需要 HTTPS 公告来源。')
        return self


def review_event(db, body):
    from .trades import lock_fund
    lock_fund(db, body.fund_code)
    event = db.scalar(select(DividendEvent).where(DividendEvent.fund_code == body.fund_code,
        DividendEvent.record_date == body.record_date))
    if not event:
        raise ValueError('请先同步官网分红记录，再核验对应公告。')
    if event.status == 'conflict' or event.cash_per_share != body.cash_per_share or event.pay_date != body.pay_date:
        raise ValueError('公告与已保存来源冲突，禁止覆盖权益记录。')
    evidence = {'review': body.model_dump(mode='json'), 'policy_note': POLICY_NOTE,
                'observation': event.evidence.get('observation', event.evidence)}
    if event.status == 'verified':
        if event.evidence.get('review') != evidence['review']:
            raise ValueError('已核验公告不可静默修改。')
        return event
    event.ex_date, event.status, event.evidence = body.ex_date, 'verified', evidence
    db.flush()
    return event


def observe_events(db, fund, official, observed_at, source_url):
    """Official table lacks ex-dates: store candidates, never auto-approve payouts."""
    seen = set()
    for row in official.get('dividend_rows', []):
        if len(row) != 4 or not row[0] or row[0] == '暂无数据':
            if row and any('暂无数据' in cell for cell in row):
                continue
            raise ValueError('分红表字段不完整。')
        record, pay = date.fromisoformat(row[0]), date.fromisoformat(row[3])
        amount = Decimal(row[2])
        if record in seen or not amount.is_finite() or not 0 < amount < 1000 or amount != amount.quantize(Decimal('.00000001')) or pay < record:
            raise ValueError('分红来源日期、金额或精度异常。')
        seen.add(record)
        event = db.scalar(select(DividendEvent).where(DividendEvent.fund_code == fund.code, DividendEvent.record_date == record))
        observation = {'row': row, 'url': source_url, 'observed_at': observed_at.isoformat()}
        if event:
            if event.pay_date != pay or event.cash_per_share != amount:
                event.status = 'conflict'
                if not any(c.get('row') == row for c in event.conflicts):
                    event.conflicts = [*event.conflicts, observation]
        else:
            db.add(DividendEvent(fund_code=fund.code, record_date=record, pay_date=pay,
                cash_per_share=amount, source_url=source_url, observed_at=observed_at,
                evidence={'observation': observation}))
    db.flush()


def eligible_shares(db, account_id, event):
    """Rebuild record-date ownership from immutable buys and sale allocations, including exited lots."""
    if db.scalar(select(BuyOrder.id).where(BuyOrder.account_id == account_id,
            BuyOrder.fund_code == event.fund_code, BuyOrder.trade_date < event.record_date,
            BuyOrder.status == 'pending').limit(1)):
        return None
    if db.scalar(select(SellOrder.id).where(SellOrder.account_id == account_id,
            SellOrder.fund_code == event.fund_code, SellOrder.trade_date < event.record_date,
            SellOrder.status == 'pending').limit(1)):
        return None
    lots = db.scalars(select(PositionLot).join(BuyOrder, BuyOrder.id == PositionLot.order_id).where(
        PositionLot.account_id == account_id, PositionLot.fund_code == event.fund_code,
        BuyOrder.trade_date < event.record_date)).all()
    allocations, total = [], Decimal('0.00')
    for lot in lots:
        sold = db.scalar(select(func.coalesce(func.sum(SellAllocation.shares), 0)).join(SellOrder).where(
            SellAllocation.lot_id == lot.id, SellOrder.status.in_(['confirmed', 'paid']),
            SellOrder.trade_date < event.record_date))
        shares = lot.shares - sold
        if shares < 0:
            raise ValueError('登记日份额对账失败。')
        total += shares
        allocations.append({'lot_id': str(lot.id), 'shares': str(shares)})
    return total, allocations


def unsupported_notes(db, account_id, event):
    first_trade = db.scalar(select(func.min(BuyOrder.trade_date)).where(BuyOrder.account_id == account_id,
        BuyOrder.fund_code == event.fund_code, BuyOrder.status == 'confirmed'))
    if first_trade is None:
        return False
    notes = db.scalars(select(FundNav).where(FundNav.fund_code == event.fund_code,
        FundNav.nav_date > first_trade, FundNav.nav_date <= event.ex_date,
        FundNav.dividend_note.is_not(None), FundNav.dividend_note != '')).all()
    for nav in notes:
        known = db.scalar(select(DividendEvent).where(DividendEvent.fund_code == event.fund_code,
            DividendEvent.ex_date == nav.nav_date, DividendEvent.status == 'verified'))
        if not known or not cash_note_matches(nav.dividend_note, known.cash_per_share):
            return True
    return False


def settle_dividends(db, account_id, clock=utcnow):
    from .trades import lock_account, lock_fund
    from .redemptions import source_problem
    account = lock_account(db, account_id)
    now = clock()
    today = now.astimezone(CN).date()
    codes = select(BuyOrder.fund_code).where(BuyOrder.account_id == account_id)
    events = db.scalars(select(DividendEvent).where(DividendEvent.fund_code.in_(codes),
        DividendEvent.status == 'verified', DividendEvent.ex_date <= today).order_by(DividendEvent.ex_date, DividendEvent.id)).all()
    paid = 0
    for candidate in events:
        lock_fund(db, candidate.fund_code)
        event = db.get(DividendEvent, candidate.id, populate_existing=True)
        if event.status != 'verified':
            continue
        payment = db.scalar(select(DividendPayment).where(DividendPayment.account_id == account_id, DividendPayment.event_id == event.id))
        if not payment:
            # Official ex-date NAV is needed so assets never add a receivable to a pre-distribution value.
            nav = db.get(FundNav, (event.fund_code, event.ex_date))
            if source_problem(db, event.fund_code) or not nav:
                continue
            if nav.dividend_note and not cash_note_matches(nav.dividend_note, event.cash_per_share):
                continue
            if unsupported_notes(db, account_id, event):
                continue
            result = eligible_shares(db, account_id, event)
            if result is None:
                continue
            shares, allocations = result
            if shares == 0:
                continue
            payment = DividendPayment(account_id=account_id, event_id=event.id, shares=shares,
                amount=rounded(shares * event.cash_per_share), created_at=now,
                snapshot={'policy': POLICY, 'note': POLICY_NOTE, 'evidence': event.evidence,
                    'record_date': event.record_date.isoformat(), 'ex_date': event.ex_date.isoformat(),
                    'pay_date': event.pay_date.isoformat(), 'cash_per_share': str(event.cash_per_share),
                    'allocations': allocations})
            db.add(payment); db.flush()
        if payment.status == 'pending' and today >= event.pay_date:
            account.available_cash += payment.amount
            db.add(CashLedger(account_id=account_id, event_key=f'dividend_paid:{payment.id}', kind='dividend_paid',
                amount=payment.amount, available_delta=payment.amount, balance_after=account.available_cash,
                reserved_after=account.reserved_cash, redemption_after=account.redemption_cash, created_at=now))
            payment.status, payment.paid_at = 'paid', now
            paid += 1
            db.flush()
    return paid


def dividend_totals(db, account_id):
    payments = db.scalars(select(DividendPayment).where(DividendPayment.account_id == account_id)).all()
    return (sum((p.amount for p in payments if p.status == 'pending'), Decimal('0.00')),
            sum((p.amount for p in payments), Decimal('0.00')))


@router.get('/account/dividends')
def payments(user: CurrentUser, db: DB):
    account = owned_account(db, user)
    rows = db.execute(select(DividendPayment, DividendEvent).join(DividendEvent).where(
        DividendPayment.account_id == account.id, DividendPayment.shares > 0)
        .order_by(DividendEvent.record_date.desc())).all()
    return {'policy_note': POLICY_NOTE, 'items': [{'id': str(p.id), 'fund_code': e.fund_code,
        'record_date': e.record_date, 'ex_date': e.ex_date, 'pay_date': e.pay_date,
        'shares': str(p.shares), 'cash_per_share': p.snapshot['cash_per_share'], 'amount': str(p.amount),
        'status': p.status, 'paid_at': p.paid_at, 'source_url': p.snapshot['evidence']['review']['source_url'],
        'warning': '来源已出现冲突，已保存金额等待人工对账。' if e.status == 'conflict' else ''} for p, e in rows]}


def main():
    parser = argparse.ArgumentParser(description='导入经人工核验的现金分红公告；不直接触发到账。')
    parser.add_argument('file', type=Path, nargs='?')
    parser.add_argument('--list', action='store_true', help='列出已同步的分红事件及核验状态')
    parser.add_argument('--code', help='按六位基金代码筛选分红事件')
    args = parser.parse_args()
    from .db import get_engine
    with Session(get_engine()) as db:
        if args.list:
            query = select(DividendEvent).order_by(DividendEvent.record_date.desc())
            if args.code:
                query = query.where(DividendEvent.fund_code == args.code)
            for event in db.scalars(query):
                print(f'{event.record_date} | 除息 {event.ex_date or "待核验"} | 发放 {event.pay_date} | 每份 {event.cash_per_share} | {event.status}')
            return
        if not args.file:
            parser.error('请提供公告 JSON 文件或 --list')
        body = ReviewedDividend.model_validate_json(args.file.read_text(encoding='utf-8-sig'))
        event = review_event(db, body)
        db.commit()
        print(f'已核验 {event.fund_code} / {event.record_date}；{POLICY_NOTE}')


if __name__ == '__main__':
    main()
