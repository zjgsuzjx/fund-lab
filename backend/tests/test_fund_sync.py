import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import delete, func, select

from app.models import Fund, FundNav, FundRuleEvidence, FundSyncRun
from app.sources import parse_history
from app.sync_funds import Transport, SourceFailure, fetch_bundle, synchronize
from test_api import db


class FakeTransport:
    def __init__(self, run_id=None, *, changed=False, invalid_page=False, malformed=False):
        self.evidence = []
        self.changed, self.invalid_page, self.malformed = changed, invalid_page, malformed
        self.rows = [{'FSRQ': (date(2024, 6, 28) - timedelta(days=i)).isoformat(), 'DWJZ': '1.2500', 'LJJZ': '1.5000'} for i in range(40)]

    def get(self, url):
        self.evidence.append({'url': url, 'sha256': 'test-response'})
        if 'fundcode_search' in url:
            return 'var r = ' + json.dumps([['000147', 'x', '测试债券A', '债券型', 'x']]) + ';'
        if 'efunds.com.cn' in url:
            nav_rows = ''.join(f"<tr><td>{r['FSRQ']}</td><td>{r['DWJZ']}</td><td>0</td><td>{r['LJJZ']}</td></tr>" for r in self.rows[:10])
            return '<table class="baseinfo-table"><tr><td>基金代码</td><td>000147</td></tr></table>' + '<table class="table_feilv"><tr><th>申购费率</th></tr><tr><td>M&lt;100万</td><td>0.80%</td></tr></table>' + '<table class="table_feilv"><tr><th>赎回费率</th></tr><tr><td>0-6</td><td>1.50%</td></tr></table>' + '<table><tr><th>日期</th><th>单位净值(元)</th></tr>' + nav_rows + '</table>'
        page = int(parse_qs(urlparse(url).query)['pageIndex'][0])
        rows = [dict(r) for r in self.rows[(page - 1) * 20:page * 20]]
        if self.invalid_page and page == 2:
            rows = self.rows[:20]
        if self.malformed:
            rows[0]['DWJZ'] = 'NaN'
        if self.changed and page == 2:
            rows[-1]['DWJZ'] = '1.2600'
        return json.dumps({'ErrCode': 0, 'TotalCount': 40, 'Data': {'LSJZList': rows}})


@pytest.fixture
def clean_fund(db):
    # Only fixture-local changes: outer rollback restores all real history.
    db.execute(delete(FundNav).where(FundNav.fund_code == '000147'))
    fund = db.get(Fund, '000147')
    fund.last_sync_at = None; fund.is_sample = True; fund.history_complete = False
    db.flush()
    return db


@pytest.mark.integration
def test_sync_repeatable_full_history_and_rule_provenance(clean_fund):
    db = clean_fund
    first = synchronize(db, '000147', transport_factory=FakeTransport)
    assert first['status'] == 'success' and first['inserted'] == 40
    second = synchronize(db, '000147', transport_factory=FakeTransport)
    assert second['status'] == 'success' and second['inserted'] == 0
    assert db.scalar(select(func.count()).select_from(FundNav).where(FundNav.fund_code == '000147')) == 40
    fund = db.get(Fund, '000147')
    assert not fund.is_sample and fund.history_complete and not fund.trade_enabled
    rules = db.get(FundRuleEvidence, '000147')
    assert not rules.is_snapshot and rules.subscription_fees[0][1] == '0.80%'
    assert rules.observed_at is not None


@pytest.mark.integration
def test_revision_conflict_preserves_cash_and_old_nav(clean_fund):
    db = clean_fund
    assert synchronize(db, '000147', transport_factory=FakeTransport)['status'] == 'success'
    before = db.get(Fund, '000147').last_sync_at
    result = synchronize(db, '000147', full=True, transport_factory=lambda rid: FakeTransport(rid, changed=True))
    assert result['status'] == 'conflict'
    values = db.scalars(select(FundNav.unit_nav).where(FundNav.fund_code == '000147')).all()
    assert set(values) == {Decimal('1.2500')}
    assert db.get(Fund, '000147').last_sync_at == before
    run = db.scalar(select(FundSyncRun).where(FundSyncRun.fund_code == '000147', FundSyncRun.status == 'conflict').order_by(FundSyncRun.started_at.desc()))
    assert run.conflicts[0]['new_unit_nav'] == '1.2600' and len(run.evidence) >= 4


@pytest.mark.integration
def test_invalid_sync_leaves_no_partial_rows(clean_fund):
    db = clean_fund
    for settings in [{'invalid_page': True}, {'malformed': True}]:
        result = synchronize(db, '000147', transport_factory=lambda rid: FakeTransport(rid, **settings))
        assert result['status'] == 'failed'
        assert db.scalar(select(func.count()).select_from(FundNav).where(FundNav.fund_code == '000147')) == 0
        assert db.get(Fund, '000147').is_sample
    assert synchronize(db, '000147', transport_factory=FakeTransport)['status'] == 'success'


def test_inconsistent_upstream_identity_and_dates():
    with pytest.raises(SourceFailure):
        fetch_bundle('000148', FakeTransport())
    for value in ['NaN', 'Infinity', '-1', '0']:
        with pytest.raises((ValueError, ArithmeticError)):
            parse_history(json.dumps({'TotalCount': 1, 'Data': {'LSJZList': [{'FSRQ': '2024-01-01', 'DWJZ': value}]}}))


def test_transport_retries_and_saves_raw_evidence(tmp_path, monkeypatch):
    import app.sync_funds as sync
    calls = []
    def request(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise URLError('offline test')
        return io.BytesIO(b'{"source":"test"}')
    monkeypatch.setattr(sync, 'urlopen', request)
    monkeypatch.setattr(sync.time, 'sleep', lambda seconds: None)
    transport = Transport('test', raw_root=tmp_path)
    assert json.loads(transport.get('https://example.com/source'))['source'] == 'test'
    assert len(calls) == 3 and len(transport.evidence) == 1
    evidence = transport.evidence[0]
    assert (tmp_path / 'test' / evidence['file']).read_bytes() == b'{"source":"test"}'
    assert len(evidence['sha256']) == 64
    assert (tmp_path / 'test' / 'manifest.json').exists()


@pytest.mark.integration
def test_concurrent_sync_lock_skips_second_worker():
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.db import get_engine
    with Session(get_engine()) as first, Session(get_engine()) as second:
        try:
            first.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 81000000 + 147})
            result = synchronize(second, '000147', transport_factory=lambda _: pytest.fail('locked worker must not fetch'))
            assert result['status'] == 'busy'
        finally:
            first.rollback()
            second.rollback()


def test_sync_does_not_erase_known_dividend_annotation(clean_fund):
    db = clean_fund
    synchronize(db, '000147', transport_factory=FakeTransport)
    nav = db.get(FundNav, ('000147', date(2024, 6, 28)))
    nav.dividend_note = '每份派现金0.1元'
    db.commit()
    result = synchronize(db, '000147', transport_factory=FakeTransport)
    assert result['status'] == 'conflict'
    assert nav.dividend_note == '每份派现金0.1元'


def test_official_dividend_candidates_are_idempotent_and_conflicts_persist(clean_fund):
    from app.dividends import observe_events
    from app.models import DividendEvent
    db = clean_fund
    fund = db.get(Fund, '000147')
    now = datetime.now(timezone.utc)
    data = {'dividend_rows': [['2024-06-28', '2024-06-20', '0.1', '2024-07-01']]}
    for _ in range(2):
        observe_events(db, fund, data, now, fund.source_url)
    event = db.scalar(select(DividendEvent).where(DividendEvent.fund_code == '000147', DividendEvent.record_date == date(2024, 6, 28)))
    assert event.status == 'observed' and event.ex_date is None
    data['dividend_rows'][0][2] = '0.2'
    observe_events(db, fund, data, now, fund.source_url)
    assert event.status == 'conflict' and event.cash_per_share == Decimal('.1')
    data['dividend_rows'][0][2] = '0.1'
    observe_events(db, fund, data, now, fund.source_url)
    assert event.status == 'conflict'
