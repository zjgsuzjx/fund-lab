"""Explicit local activation of the reviewed simulation profile, after a successful sync."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_engine
from .models import Fund, FundSyncRun
from .trade_rules import RULE, disabled_reason
from .trades import lock_fund


def enable():
    with Session(get_engine()) as db:
        lock_fund(db, RULE['fund_code'])
        fund = db.get(Fund, RULE['fund_code'])
        run = db.scalar(select(FundSyncRun).where(FundSyncRun.fund_code == RULE['fund_code'])
                        .order_by(FundSyncRun.started_at.desc()).limit(1))
        if not fund or not run or run.status != 'success':
            raise SystemExit('请先成功同步 000147，再启用模拟规则。')
        fund.trade_enabled = True
        if reason := disabled_reason(fund):
            raise SystemExit(reason)
        db.commit()
    print(f"已启用 {RULE['version']}；这是本地公开标准费率模拟方案。")


if __name__ == '__main__':
    enable()
