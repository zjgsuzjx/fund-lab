"""Explicit local activation of the reviewed simulation profile, after a successful sync."""
import argparse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_engine
from .models import Fund, FundSyncRun
from .trade_rules import RULE, disabled_reason, rule_for
from .trades import lock_fund


def enable(code=RULE['fund_code']):
    with Session(get_engine()) as db:
        lock_fund(db, code)
        fund = db.get(Fund, code)
        run = db.scalar(select(FundSyncRun).where(FundSyncRun.fund_code == code)
                        .order_by(FundSyncRun.started_at.desc()).limit(1))
        if not fund or not run or run.status != 'success':
            raise SystemExit(f'请先成功同步 {code}，再启用模拟规则。')
        fund.trade_enabled = True
        if reason := disabled_reason(fund):
            raise SystemExit(reason)
        db.commit()
        version = rule_for(fund)['version']
    print(f"已启用 {version}；具体模拟假设见基金详情。")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code', default=RULE['fund_code'])
    args = parser.parse_args()
    if len(args.code) != 6 or not args.code.isascii() or not args.code.isdigit():
        parser.error('需要六位基金代码')
    enable(args.code)
