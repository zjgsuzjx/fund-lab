"""Persistent update requests and bounded polling. Session locks survive sync commits."""
from datetime import datetime, time, timedelta
from functools import partial
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text, func, or_, case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .auth import CurrentUser, DB, write_guard
from .db import get_engine
from .models import DataUpdateJob, Fund, Watchlist, BuyOrder, PositionLot, SellOrder, MarketSyncState
from .sync_funds import synchronize, sync_directory, Transport
from .trade_rules import CN, utcnow

router = APIRouter(prefix='/api/data')
CODE = '000147'
LOCK_KEY = 92000147


def serialize(job, code=CODE):
    return {'fund_code': job.fund_code if job else code, 'status': job.status if job else 'idle',
        'requested_at': job.requested_at if job else None,
        'started_at': job.started_at if job else None, 'finished_at': job.finished_at if job else None,
        'message': job.message if job else '服务运行时每 6 小时检查更新；失败 15 分钟后重试。'}


def request_update(db, now, code=CODE):
    fund = db.get(Fund, code)
    if not fund:
        raise HTTPException(409, '请先初始化基金目录。')
    if '货币' in fund.category:
        raise HTTPException(409, '货币基金使用万份收益模型，目前仅展示目录。')
    db.execute(insert(DataUpdateJob).values(fund_code=code, requested_at=now, status='queued', message='已排队，稍后开始更新。')
        .on_conflict_do_nothing())
    job = db.scalar(select(DataUpdateJob).where(DataUpdateJob.fund_code == code).with_for_update())
    if job.status in ('queued', 'running'):
        return job
    if job.finished_at and now - job.finished_at < timedelta(minutes=5):
        raise HTTPException(429, '刚刚更新过，请 5 分钟后再试。')
    job.requested_at, job.status, job.message = now, 'queued', '已排队，稍后开始更新。'
    return job


@router.get('/update')
def status(db: DB, code: str = Query(default=CODE, pattern=r'^[0-9]{6}$')):
    return serialize(db.get(DataUpdateJob, code), code)


@router.post('/update', status_code=202, dependencies=[Depends(write_guard)])
def enqueue(user: CurrentUser, db: DB, code: str = Query(default=CODE, pattern=r'^[0-9]{6}$')):
    job = request_update(db, utcnow(), code)
    db.commit()
    return serialize(job)


def run_update(db, now, synchronize_fn=synchronize, *, code=CODE, scheduled=False):
    fund = db.get(Fund, code)
    if not fund:
        return {'status': 'uninitialized'}
    job = db.get(DataUpdateJob, code)
    if job and job.status != 'queued':
        delay = timedelta(minutes=15) if job.status in ('failed', 'busy', 'running') else timedelta(hours=6)
        anchor = job.finished_at or job.started_at
        if scheduled and job.status == 'success':
            delay = now - scheduled_slot(now)
        if anchor and now - anchor < delay:
            return serialize(job)
    elif not scheduled and not job and fund.last_sync_at and now - fund.last_sync_at < timedelta(hours=6):
        return {'status': 'fresh'}
    if not job:
        job = DataUpdateJob(fund_code=code, requested_at=now)
        db.add(job)
    job.status, job.started_at, job.finished_at, job.message = 'running', now, None, '正在核对官网与净值来源。'
    db.commit()
    try:
        result = synchronize_fn(db, code)
    except Exception:
        db.rollback()
        result = {'status': 'failed', 'message': '更新中断，保留已有数据，15 分钟后重试。'}
    job = db.get(DataUpdateJob, code, populate_existing=True)
    job.status, job.finished_at, job.message = result['status'], now, result.get('message', '更新结束。')
    db.commit()
    return serialize(job)


def scheduled_slot(now):
    local = now.astimezone(CN)
    # NAV publication varies: evening run and next-morning catch-up.
    slots = [datetime.combine(local.date(), time(hour), CN) for hour in (8, 20, 23)]
    return max([s for s in slots if s <= local] or [slots[-1] - timedelta(days=1)])


def refresh_market(db, now):
    from .trading_calendar import sync_calendar
    for key, operation in (('catalog', lambda t: sync_directory(db, t)), ('calendar', sync_calendar)):
        state = db.get(MarketSyncState, key)
        delay = timedelta(days=1) if state and state.status == 'success' else timedelta(minutes=15)
        if state and now - state.attempted_at < delay:
            continue
        try:
            value = operation(Transport(uuid4()))
            result, message = 'success', f'已更新：{value}'
        except Exception:
            db.rollback()
            result, message = 'failed', '来源不可用或校验失败，保留缓存，15 分钟后重试。'
        state = db.get(MarketSyncState, key)
        if not state:
            state = MarketSyncState(key=key)
            db.add(state)
        state.attempted_at, state.status, state.message = now, result, message
        if result == 'success':
            state.succeeded_at = now
        db.commit()


def due_codes(db, now, limit=20):
    # Manual requests, owned funds and watchlists precede the daily whole-market sweep.
    tracked = or_(Fund.code.in_(select(Watchlist.fund_code)),
                  Fund.code.in_(select(PositionLot.fund_code).where(PositionLot.remaining_shares > 0)),
                  Fund.code.in_(select(BuyOrder.fund_code).where(BuyOrder.status == 'pending')),
                  Fund.code.in_(select(SellOrder.fund_code).where(SellOrder.status.in_(['pending', 'confirmed']))))
    anchor = func.coalesce(DataUpdateJob.finished_at, DataUpdateJob.started_at)
    due = or_(DataUpdateJob.status == 'queued',
              (DataUpdateJob.status.in_(['failed', 'busy', 'running']) &
               or_(anchor.is_(None), anchor <= now - timedelta(minutes=15))),
              (or_(DataUpdateJob.status.is_(None), DataUpdateJob.status == 'success') &
               or_(Fund.last_sync_at.is_(None),
                   Fund.last_sync_at < case((tracked, scheduled_slot(now)), else_=now - timedelta(days=1)))))
    return list(db.scalars(select(Fund.code).outerjoin(DataUpdateJob)
        .where(~Fund.category.contains('货币'), due,
               or_(Fund.source_url.like('https://fundf10.eastmoney.com/%'),
                   Fund.source_url.like('https://www.efunds.com.cn/%')))
        .order_by(case((DataUpdateJob.status == 'queued', 0), (tracked, 1), else_=2),
                  Fund.last_sync_at.asc().nullsfirst(), Fund.code).limit(limit)))


def tracked_codes(db):
    result = set(db.scalars(select(Watchlist.fund_code)))
    result.update(db.scalars(select(PositionLot.fund_code).where(PositionLot.remaining_shares > 0)))
    result.update(db.scalars(select(BuyOrder.fund_code).where(BuyOrder.status == 'pending')))
    result.update(db.scalars(select(SellOrder.fund_code).where(SellOrder.status.in_(['pending', 'confirmed']))))
    result.update(db.scalars(select(DataUpdateJob.fund_code).where(DataUpdateJob.status == 'queued')))
    return result


@router.get('/coverage')
def coverage(db: DB):
    now = utcnow()
    counts = dict(db.execute(select(DataUpdateJob.status, func.count()).group_by(DataUpdateJob.status)).all())
    states = db.scalars(select(MarketSyncState)).all()
    return {'fund_count': db.scalar(select(func.count()).select_from(Fund)),
            'synced_count': db.scalar(select(func.count()).select_from(Fund).where(Fund.last_sync_at.is_not(None))),
            'fresh_count': db.scalar(select(func.count()).select_from(Fund).where(Fund.last_sync_at >= now - timedelta(days=1))),
            'jobs': counts, 'schedule': '北京时间 08:00、20:00、23:00 优先同步持仓、自选及在途基金；其余净值型基金每日轮询。',
            'sources': [{'key': s.key, 'status': s.status, 'message': s.message,
                         'succeeded_at': s.succeeded_at} for s in states]}


def update_due():
    # One connected worker owns the network operation. Process death releases
    # the lock; its durable running job is retried after the 15-minute lease.
    with get_engine().connect() as connection:
        locked = connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_KEY})
        connection.commit()
        if not locked:
            return {'status': 'busy'}
        try:
            with Session(bind=connection) as db:
                now = utcnow()
                refresh_market(db, now)
                codes = due_codes(db, now)
                for code in codes:
                    run_update(db, utcnow(), partial(synchronize, cached_directory=True, bootstrap_days=400),
                               code=code, scheduled=True)
                return {'status': 'success', 'processed': len(codes)}
        finally:
            connection.rollback()
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_KEY})
            connection.commit()
