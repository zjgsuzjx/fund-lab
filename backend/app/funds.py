"""Read-only public catalogue and session-owned watchlists."""
import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert

from .auth import COOKIE, DB, CurrentUser, current_user, write_guard
from .models import Fund, FundNav, FundRuleEvidence, FundSyncRun, Watchlist

from .trade_rules import disabled_reason, rule_snapshot

router = APIRouter(prefix='/api')
Period = Literal['1m', '3m', '1y', 'all']


def optional_user(request: Request, db: DB):
    if not request.cookies.get(COOKIE):
        return None
    try:
        return current_user(request, db)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return None


def months_before(day: date, months: int):
    total = day.year * 12 + day.month - 1 - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def category_group(category: str):
    return 'bond' if '债券' in category else 'index' if '指数' in category else 'mixed' if '混合' in category else 'other'


def require_fund(db, code):
    fund = db.get(Fund, code) if re.fullmatch(r'[0-9]{6}', code) else None
    if not fund:
        raise HTTPException(404, '未找到这只基金，请返回发现页重新选择。')
    return fund


def serialize_fund(fund, navs, watched=False):
    latest = navs[-1] if navs else None
    year_change = None
    if latest:
        cutoff = months_before(latest.nav_date, 12)
        base = next((n for n in reversed(navs) if n.nav_date <= cutoff), None)
        # A recent baseline is necessary; old sparse seed points are not a full year.
        if base and (cutoff - base.nav_date).days <= 10 and not fund.is_sample:
            year_change = str(((latest.unit_nav / base.unit_nav - 1) * 100).quantize(Decimal('0.01')))
    share = re.search(r'([A-Z])$', fund.name)
    return {'code': fund.code, 'name': fund.name, 'category': fund.category,
            'category_group': category_group(fund.category), 'share_class': share[1] if share else None,
            'nav_date': latest.nav_date if latest else None, 'unit_nav': str(latest.unit_nav) if latest else None,
            'year_change': year_change, 'change_basis': '单位净值涨跌，不含分红再投资',
            'source_observed_at': fund.source_observed_at, 'last_sync_at': fund.last_sync_at,
            'is_sample': fund.is_sample, 'trade_enabled': not disabled_reason(fund), 'is_watched': watched,
            'history_complete': fund.history_complete,
            'trade_disabled_reason': disabled_reason(fund)}


@router.get('/funds')
def list_funds(db: DB, request: Request,
               q: Annotated[str, Query(max_length=100)] = '',
               category: Literal['all', 'bond', 'index', 'mixed'] = 'all',
               sort: Literal['code', 'name', 'nav_desc', 'change_desc', 'change_asc'] = 'code',
               watchlist: bool = False,
               page: Annotated[int, Query(ge=1)] = 1,
               page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    user = optional_user(request, db)
    if watchlist and not user:
        raise HTTPException(401, '请先登录后查看自选基金。')
    query = select(Fund)
    if q.strip():
        query = query.where(or_(Fund.code.contains(q.strip(), autoescape=True), Fund.name.contains(q.strip(), autoescape=True)))
    if category != 'all':
        query = query.where(Fund.category.contains({'bond': '债券', 'index': '指数', 'mixed': '混合'}[category]))
    watched = set(db.scalars(select(Watchlist.fund_code).where(Watchlist.user_id == user.id))) if user else set()
    if watchlist:
        query = query.where(Fund.code.in_(watched))
    funds = db.scalars(query.order_by(Fund.code)).all()
    # The curated pool is deliberately small. Batch reads avoid per-row queries.
    navs = {}
    for nav in db.scalars(select(FundNav).where(FundNav.fund_code.in_([f.code for f in funds])).order_by(FundNav.nav_date)):
        navs.setdefault(nav.fund_code, []).append(nav)
    items = [serialize_fund(f, navs.get(f.code, []), f.code in watched) for f in funds]
    if sort == 'name':
        items.sort(key=lambda f: (f['name'], f['code']))
    elif sort != 'code':
        key = 'unit_nav' if sort == 'nav_desc' else 'year_change'
        direction = 1 if sort == 'change_asc' else -1
        items.sort(key=lambda f: (f[key] is None, direction * Decimal(f[key] or '0'), f['code']))
    return {'items': items[(page - 1) * page_size:page * page_size], 'total': len(items), 'page': page, 'page_size': page_size}


@router.get('/funds/{code}')
def detail(code: str, db: DB, request: Request):
    fund = require_fund(db, code)
    user = optional_user(request, db)
    navs = db.scalars(select(FundNav).where(FundNav.fund_code == code).order_by(FundNav.nav_date)).all()
    result = serialize_fund(fund, navs, bool(user and db.get(Watchlist, (user.id, code))))
    evidence = db.get(FundRuleEvidence, code)
    result.update(source_url=fund.source_url,
                  nav_source_url=f'https://fundf10.eastmoney.com/jjjz_{code}.html',
                  earliest_nav_date=navs[0].nav_date if navs else None, history_count=len(navs),
                  rules={'status': 'incomplete', 'source_url': evidence.source_url if evidence else fund.source_url,
                         'observed_at': evidence.observed_at if evidence else None,
                         'is_snapshot': evidence.is_snapshot if evidence else True,
                         'subscription_fees': evidence.subscription_fees if evidence else [],
                         'redemption_fees': evidence.redemption_fees if evidence else [],
                         'ongoing_fees': evidence.ongoing_fees if evidence else [],
                         'minimum_purchase': None, 'confirmation': None, 'arrival': None,
                         'note': '基金公司公开标准费率，仅供了解；非支付宝渠道优惠费率。起购限制、规则生效日、确认与到账日历仍待核验。'})
    if not disabled_reason(fund):
        result['rules'].update(status='simulation_verified', minimum_purchase='1.00 元',
                               confirmation='T+1 起，等待正式净值',
                               arrival='赎回 T+7 到账（本模拟方案约定）', note=rule_snapshot()['scope'])
        result['simulation_rule'] = rule_snapshot()
    return result


@router.get('/funds/{code}/nav')
def history(code: str, db: DB, period: Period = '1y'):
    fund = require_fund(db, code)
    rows = db.scalars(select(FundNav).where(FundNav.fund_code == code).order_by(FundNav.nav_date)).all()
    if not rows:
        return {'items': [], 'period': period, 'complete': False, 'change': None, 'message': '暂无净值数据。', 'basis': '单位净值涨跌，不含分红再投资'}
    cutoff = months_before(rows[-1].nav_date, {'1m': 1, '3m': 3, '1y': 12}[period]) if period != 'all' else None
    baseline = next((r for r in reversed(rows) if cutoff and r.nav_date <= cutoff), None)
    complete = (fund.history_complete if period == 'all' else bool(baseline and (cutoff - baseline.nav_date).days <= 10)) and not fund.is_sample
    selected = rows if cutoff is None else [r for r in rows if r.nav_date >= (baseline.nav_date if baseline else cutoff)]
    change = str(((selected[-1].unit_nav / selected[0].unit_nav - 1) * 100).quantize(Decimal('0.01'))) if complete and len(selected) > 1 else None
    return {'items': [{'date': r.nav_date, 'unit_nav': str(r.unit_nav), 'dividend_note': r.dividend_note} for r in selected],
            'period': period, 'complete': complete, 'change': change,
            'message': '' if complete else ('当前仅展示已获取历史，尚非成立以来完整数据。' if period == 'all' else '该区间历史数据不足，暂不计算区间涨跌。'),
            'basis': '单位净值涨跌，不含分红再投资', 'end_date': rows[-1].nav_date}


class WatchAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool


@router.post('/watchlist/{code}', dependencies=[Depends(write_guard)])
def set_watchlist(code: str, body: WatchAction, db: DB, user: CurrentUser):
    require_fund(db, code)
    if body.enabled:
        db.execute(insert(Watchlist).values(user_id=user.id, fund_code=code).on_conflict_do_nothing())
    else:
        db.execute(delete(Watchlist).where(Watchlist.user_id == user.id, Watchlist.fund_code == code))
    db.commit()
    return {'fund_code': code, 'is_watched': body.enabled}


@router.get('/data/sync-runs')
def sync_runs(db: DB):
    runs = db.scalars(select(FundSyncRun).order_by(FundSyncRun.started_at.desc()).limit(20)).all()
    return {'items': [{'id': str(r.id), 'fund_code': r.fund_code, 'status': r.status,
                       'started_at': r.started_at, 'finished_at': r.finished_at, 'inserted': r.inserted,
                       'unchanged': r.unchanged, 'message': r.message} for r in runs]}
