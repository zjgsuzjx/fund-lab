"""Idempotent database-only settlement. Run once or via the API lifespan worker."""
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_engine
from .models import BuyOrder
from .trades import settle_buy
from .trade_rules import CN, utcnow

log = logging.getLogger(__name__)


def settle_pending():
    with Session(get_engine()) as db:
        # Short transactions per order, so one bad record cannot roll back others.
        pending = db.execute(select(BuyOrder.account_id, BuyOrder.id).where(
            BuyOrder.status == 'pending', BuyOrder.confirmation_date <= utcnow().astimezone(CN).date())
            .order_by(BuyOrder.created_at)).all()
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
    return {'checked': len(pending), 'confirmed_or_already_confirmed': confirmed, 'errors': errors}


if __name__ == '__main__':
    result = settle_pending()
    print(result)
    raise SystemExit(1 if result['errors'] else 0)
