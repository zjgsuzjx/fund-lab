"""Load only the five verified domestic candidates as dated, non-tradable samples."""
import json
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from .config import ROOT
from .db import get_engine
from .models import Fund, FundNav


def seed(session: Session):
    report = json.loads((ROOT / 'data/validation/fund-source-snapshot-2026-09-13.json').read_text(encoding='utf-8'))
    for item in report['funds']:
        if item['classification'] != 'candidate_not_trade_enabled':
            continue
        # Never overwrite later syncs or existing user data when re-running setup.
        added = session.scalar(insert(Fund).values(code=item['code'], name=item['name'], category=item['directory_type'],
            source_url=item['sources']['official'], source_observed_at=datetime.fromisoformat(report['run_at_utc']),
            is_sample=True, trade_enabled=False).on_conflict_do_nothing().returning(Fund.code))
        if added is None:
            continue
        for nav in item['latest_samples']:
            session.execute(insert(FundNav).values(fund_code=item['code'], nav_date=date.fromisoformat(nav['date']),
                unit_nav=Decimal(nav['unit_nav']), cumulative_nav=Decimal(nav['cumulative_nav']) if nav['cumulative_nav'] else None
            ).on_conflict_do_nothing())


if __name__ == '__main__':
    with Session(get_engine()) as session, session.begin():
        seed(session)
    print('Sample import complete (existing records preserved; trading disabled).')
