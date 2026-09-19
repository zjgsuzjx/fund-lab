from datetime import timedelta

import pytest
from sqlalchemy import delete

from app.maintenance import request_update, run_update
from app.models import DataUpdateJob, Fund
from test_api import db
from test_auth import client, credentials
from test_redemptions import NOW


def test_update_requires_login_and_deduplicates_requests(client, db):
    db.execute(delete(DataUpdateJob))
    assert client.post('/api/data/update', json={}).status_code == 401
    client.post('/api/auth/register', json=credentials()).raise_for_status()
    first = client.post('/api/data/update', json={})
    assert first.status_code == 202
    second = client.post('/api/data/update', json={})
    assert second.json()['requested_at'] == first.json()['requested_at']
    assert client.get('/api/data/update').json()['status'] == 'queued'


def test_update_schedule_failure_retry_and_crash_recovery(db):
    db.execute(delete(DataUpdateJob))
    db.get(Fund, '000147').last_sync_at = None
    calls = []
    def fail(session, code):
        calls.append(code)
        return {'status': 'failed', 'message': 'test offline'}
    assert run_update(db, NOW, fail)['status'] == 'failed'
    run_update(db, NOW + timedelta(minutes=14), fail)
    assert len(calls) == 1
    def success(session, code):
        calls.append(code)
        return {'status': 'success', 'message': 'updated'}
    assert run_update(db, NOW + timedelta(minutes=15), success)['status'] == 'success'
    run_update(db, NOW + timedelta(hours=6), success)
    assert len(calls) == 2
    run_update(db, NOW + timedelta(hours=7), success)
    assert len(calls) == 3
    job = db.get(DataUpdateJob, '000147')
    job.status, job.started_at, job.finished_at = 'running', NOW, None
    db.commit()
    assert run_update(db, NOW + timedelta(minutes=16), success)['status'] == 'success'
    assert len(calls) == 4


def test_manual_update_cooldown_and_fresh_start_skip(db):
    from fastapi import HTTPException
    db.execute(delete(DataUpdateJob))
    db.get(Fund, '000147').last_sync_at = NOW
    assert run_update(db, NOW, lambda *_: pytest.fail('fresh start must not fetch'))['status'] == 'fresh'
    job = request_update(db, NOW)
    job.status, job.finished_at = 'success', NOW
    db.commit()
    with pytest.raises(HTTPException) as error:
        request_update(db, NOW + timedelta(minutes=4))
    assert error.value.status_code == 429
    assert request_update(db, NOW + timedelta(minutes=5)).status == 'queued'
