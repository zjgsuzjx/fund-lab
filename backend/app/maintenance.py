"""Persistent update requests and bounded polling. Session locks survive sync commits."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .auth import CurrentUser, DB, write_guard
from .db import get_engine
from .models import DataUpdateJob, Fund
from .sync_funds import synchronize
from .trade_rules import utcnow

router = APIRouter(prefix='/api/data')
CODE = '000147'
LOCK_KEY = 92000147


def serialize(job):
    return {'fund_code': CODE, 'status': job.status if job else 'idle',
        'requested_at': job.requested_at if job else None,
        'started_at': job.started_at if job else None, 'finished_at': job.finished_at if job else None,
        'message': job.message if job else '服务运行时每 6 小时检查更新；失败 15 分钟后重试。'}


def request_update(db, now):
    if not db.get(Fund, CODE):
        raise HTTPException(409, '请先初始化基金目录。')
    db.execute(insert(DataUpdateJob).values(fund_code=CODE, requested_at=now, status='queued', message='已排队，稍后开始更新。')
        .on_conflict_do_nothing())
    job = db.scalar(select(DataUpdateJob).where(DataUpdateJob.fund_code == CODE).with_for_update())
    if job.status in ('queued', 'running'):
        return job
    if job.finished_at and now - job.finished_at < timedelta(minutes=5):
        raise HTTPException(429, '刚刚更新过，请 5 分钟后再试。')
    job.requested_at, job.status, job.message = now, 'queued', '已排队，稍后开始更新。'
    return job


@router.get('/update')
def status(db: DB):
    return serialize(db.get(DataUpdateJob, CODE))


@router.post('/update', status_code=202, dependencies=[Depends(write_guard)])
def enqueue(user: CurrentUser, db: DB):
    job = request_update(db, utcnow())
    db.commit()
    return serialize(job)


def run_update(db, now, synchronize_fn=synchronize):
    fund = db.get(Fund, CODE)
    if not fund:
        return {'status': 'uninitialized'}
    job = db.get(DataUpdateJob, CODE)
    if job and job.status != 'queued':
        delay = timedelta(minutes=15) if job.status in ('failed', 'busy', 'running') else timedelta(hours=6)
        anchor = job.finished_at or job.started_at
        if anchor and now - anchor < delay:
            return serialize(job)
    elif not job and fund.last_sync_at and now - fund.last_sync_at < timedelta(hours=6):
        return {'status': 'fresh'}
    if not job:
        job = DataUpdateJob(fund_code=CODE, requested_at=now)
        db.add(job)
    job.status, job.started_at, job.finished_at, job.message = 'running', now, None, '正在核对官网与净值来源。'
    db.commit()
    try:
        result = synchronize_fn(db, CODE)
    except Exception:
        db.rollback()
        result = {'status': 'failed', 'message': '更新中断，保留已有数据，15 分钟后重试。'}
    job = db.get(DataUpdateJob, CODE, populate_existing=True)
    job.status, job.finished_at, job.message = result['status'], now, result.get('message', '更新结束。')
    db.commit()
    return serialize(job)


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
                return run_update(db, utcnow())
        finally:
            connection.rollback()
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_KEY})
            connection.commit()
