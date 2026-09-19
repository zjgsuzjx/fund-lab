"""Idempotent database-only settlement. Run once or via the API lifespan worker."""
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_engine
from .models import BuyOrder, SellOrder
from .dividends import settle_dividends
from .trades import settle_buy
from .redemptions import settle_sell
from .trade_rules import CN, utcnow

log = logging.getLogger(__name__)


def settle_pending(*, account_id=None):
    with Session(get_engine()) as db:
        # Short transactions per order, so one bad record cannot roll back others.
        buy_scope = [] if account_id is None else [BuyOrder.account_id == account_id]
        sell_scope = [] if account_id is None else [SellOrder.account_id == account_id]
        pending = db.execute(select(BuyOrder.account_id, BuyOrder.id).where(
            *buy_scope,
            BuyOrder.status == 'pending', BuyOrder.confirmation_date <= utcnow().astimezone(CN).date())
            .order_by(BuyOrder.created_at)).all()
        redemptions = db.execute(select(SellOrder.account_id, SellOrder.id).where(
            *sell_scope,
            SellOrder.status.in_(['pending', 'confirmed']), SellOrder.confirmation_date <= utcnow().astimezone(CN).date())
            .order_by(SellOrder.created_at)).all()
    confirmed, errors = 0, 0
    for account_id, order_id in pending:
        try:
            with Session(get_engine()) as db:
                order = settle_buy(db, account_id, order_id)
                confirmed += order.status == 'confirmed'
                db.commit()
        except Exception:
            errors += 1
            # No SQL parameters or credentials in scheduled-job logs.
            log.error('Settlement deferred for order %s', order_id)
    with Session(get_engine()) as db:
        accounts = db.scalars(select(BuyOrder.account_id).where(*buy_scope).distinct()).all()
    dividends_paid = 0
    for owner_id in accounts:
        try:
            with Session(get_engine()) as db:
                dividends_paid += settle_dividends(db, owner_id, utcnow)
                db.commit()
        except Exception:
            errors += 1
            log.error('Dividend settlement deferred for account %s', owner_id)
    paid = 0
    for account_id, order_id in redemptions:
        try:
            with Session(get_engine()) as db:
                order = settle_sell(db, account_id, order_id)
                paid += order.status == 'paid'
                db.commit()
        except Exception:
            errors += 1
            log.error('Redemption deferred for order %s', order_id)
    return {'checked': len(pending) + len(redemptions), 'confirmed_or_already_confirmed': confirmed,
            'redemptions_paid': paid, 'dividends_paid': dividends_paid, 'errors': errors}


if __name__ == '__main__':
    result = settle_pending()
    print(result)
    raise SystemExit(1 if result['errors'] else 0)
