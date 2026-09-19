"""Bounded, explicit CLI synchronization for the five verified display-only funds.

python -m app.sync_funds          # bootstrap 400 days, then overlap/incremental
python -m app.sync_funds --full   # fill all upstream history (more requests)
"""
import argparse
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import ROOT
from .db import get_engine
from .models import Fund, FundNav, FundRuleEvidence, FundSyncRun
from .sources import compare_nav, parse_directory, parse_history, parse_official

CODES = ('000147', '000148', '110020', '007339', '110009')
DIRECTORY = 'https://fund.eastmoney.com/js/fundcode_search.js'
PAGE_SIZE = 20


class SourceFailure(ValueError):
    pass


class RevisionConflict(SourceFailure):
    def __init__(self, conflicts):
        super().__init__('来源净值发生修订，已保留原值和修订记录，需人工核验。')
        self.conflicts = conflicts


class Transport:
    def __init__(self, run_id, raw_root=ROOT / 'data' / '.sync-cache'):
        self.directory = raw_root / str(run_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.evidence = []
        self.last_request = 0.0

    def get(self, url):
        for attempt in range(3):
            time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                request = Request(url, headers={'Referer': 'https://fundf10.eastmoney.com/', 'User-Agent': 'FundLab-ReadOnlySync/0.3'})
                with urlopen(request, timeout=20) as response:
                    raw = response.read(10_000_001)
                    if len(raw) > 10_000_000:
                        raise SourceFailure('来源响应超过大小限制。')
                digest = hashlib.sha256(raw).hexdigest()
                filename = f'{len(self.evidence):04d}-{digest[:12]}.raw'
                (self.directory / filename).write_bytes(raw)
                self.evidence.append({'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat(),
                                      'sha256': digest, 'bytes': len(raw), 'file': filename})
                (self.directory / 'manifest.json').write_text(json.dumps(self.evidence, ensure_ascii=False, indent=2), encoding='utf-8')
                return raw.decode('utf-8-sig')
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise SourceFailure('来源 HTTP 请求失败，稍后可重新同步。') from error
                # Respect rate limiting; do not aggressively retry 429.
                if error.code == 429:
                    raise SourceFailure('来源请求限流，请稍后重新同步。') from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt == 2:
                    raise SourceFailure('来源连接失败，已重试 3 次。') from error
            time.sleep(2 ** attempt)
        raise SourceFailure('来源请求失败。')


def fetch_bundle(code, transport, *, latest_cached=None, full=False):
    directory = parse_directory(transport.get(DIRECTORY))
    item = directory.get(code)
    if not item or 'QDII' in (item['name'] + item['type']).upper():
        raise SourceFailure('目录身份不符或产品不在已支持范围。')
    official_url = f'https://www.efunds.com.cn/fund/{code}.shtml'
    official = parse_official(transport.get(official_url))
    if official['identity'].get('基金代码') != code or not official['subscription_fees'] or not official['redemption_fees']:
        raise SourceFailure('官网身份或费率字段缺失，保留已有数据。')
    rows, expected_total, cutoff = [], None, None
    for page in range(1, 1001):
        url = 'https://api.fund.eastmoney.com/f10/lsjz?' + urlencode({'fundCode': code, 'pageIndex': page, 'pageSize': PAGE_SIZE})
        total, batch = parse_history(transport.get(url))
        if expected_total is None:
            expected_total = total
            if not 1 <= total <= PAGE_SIZE * 1000 or not batch:
                raise SourceFailure('历史净值数量异常。')
            end = date.fromisoformat(batch[0]['date'])
            cutoff = (latest_cached - timedelta(days=14)) if latest_cached else end - timedelta(days=400)
        if total != expected_total or not batch or len(batch) != min(PAGE_SIZE, total - len(rows)):
            raise SourceFailure('来源分页不完整或分页期间数据发生变化，请重新同步。')
        if rows and rows[-1]['date'] <= batch[0]['date']:
            raise SourceFailure('来源跨页日期重复或顺序错误。')
        rows.extend(batch)
        if len(rows) == total or (not full and date.fromisoformat(rows[-1]['date']) <= cutoff):
            break
    crosscheck = compare_nav(official['nav_rows'], rows)
    if not crosscheck['passed']:
        raise SourceFailure('官网与净值来源交叉核对失败，保留已有数据。')
    return {'directory': item, 'official': official, 'rows': rows, 'history_complete': len(rows) == expected_total,
            'source_url': official_url, 'observed_at': datetime.now(timezone.utc)}


def apply_bundle(db, fund, bundle):
    from .dividends import observe_events
    rows = bundle['rows']
    existing = {n.nav_date: n for n in db.scalars(select(FundNav).where(FundNav.fund_code == fund.code))}
    conflicts = []
    for row in rows:
        day = date.fromisoformat(row['date'])
        old = existing.get(day)
        unit, cumulative = Decimal(row['unit_nav']), Decimal(row['cumulative_nav']) if row['cumulative_nav'] else None
        # Validate precision before SQL Numeric could silently round.
        for value in (unit, cumulative):
            if value is not None and (not value.is_finite() or value <= 0 or value >= Decimal('1000000000000') or value != value.quantize(Decimal('0.00000001'))):
                raise SourceFailure('净值精度或数值范围异常。')
        if old and (old.unit_nav != unit or old.cumulative_nav != cumulative):
            conflicts.append({'date': row['date'], 'old_unit_nav': str(old.unit_nav), 'new_unit_nav': str(unit),
                              'old_cumulative_nav': str(old.cumulative_nav), 'new_cumulative_nav': str(cumulative)})
        if old and old.dividend_note and old.dividend_note != row.get('dividend_note'):
            conflicts.append({'date': row['date'], 'old_dividend_note': old.dividend_note,
                              'new_dividend_note': row.get('dividend_note')})
    if conflicts:
        raise RevisionConflict(conflicts)
    inserted, unchanged = 0, 0
    for row in rows:
        day = date.fromisoformat(row['date'])
        if day in existing:
            unchanged += 1
            # Annotating an observed event does not rewrite a numeric NAV.
            existing[day].dividend_note = row.get('dividend_note')
        else:
            db.add(FundNav(fund_code=fund.code, nav_date=day, unit_nav=Decimal(row['unit_nav']),
                           cumulative_nav=Decimal(row['cumulative_nav']) if row['cumulative_nav'] else None,
                           dividend_note=row.get('dividend_note')))
            inserted += 1
    evidence = db.get(FundRuleEvidence, fund.code)
    if evidence and (evidence.subscription_fees != bundle['official']['subscription_fees'] or
                     evidence.redemption_fees != bundle['official']['redemption_fees']):
        fund.trade_enabled = False
    if not evidence:
        evidence = FundRuleEvidence(fund_code=fund.code)
        db.add(evidence)
    evidence.source_url = bundle['source_url']
    evidence.observed_at = bundle['observed_at']
    evidence.subscription_fees = bundle['official']['subscription_fees']
    evidence.redemption_fees = bundle['official']['redemption_fees']
    evidence.ongoing_fees = bundle['official']['ongoing_fees']
    evidence.is_snapshot = False
    fund.name, fund.category = bundle['directory']['name'], bundle['directory']['type']
    fund.source_url, fund.source_observed_at = bundle['source_url'], bundle['observed_at']
    fund.last_sync_at, fund.is_sample = bundle['observed_at'], False
    fund.history_complete = fund.history_complete or bundle['history_complete']
    observe_events(db, fund, bundle['official'], bundle['observed_at'], bundle['source_url'])
    db.flush()
    return inserted, unchanged


def synchronize(db, code, *, full=False, transport_factory=Transport):
    if code not in CODES:
        raise ValueError('Only the five verified candidates can be synchronized')
    fund = db.get(Fund, code)
    if not fund:
        raise ValueError('Run the seed import before syncing')
    # A transaction-scoped advisory lock prevents two CLI processes syncing the same fund.
    if not db.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': 81000000 + int(code)}):
        db.rollback()
        return {'fund_code': code, 'status': 'busy', 'message': '该基金正在同步，请稍后重试。'}
    run = FundSyncRun(id=uuid4(), fund_code=code, status='running', evidence=[], conflicts=[])
    db.add(run)
    db.flush()
    transport = None
    try:
        transport = transport_factory(run.id)
        latest = db.scalar(select(func.max(FundNav.nav_date)).where(FundNav.fund_code == code)) if fund.last_sync_at else None
        bundle = fetch_bundle(code, transport, latest_cached=latest, full=full)
        with db.begin_nested():
            run.inserted, run.unchanged = apply_bundle(db, fund, bundle)
        run.status = 'success'
        run.message = '净值与官网交叉核对通过；是否可模拟买入由已核验规则控制。'
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError) as error:
        run.status = 'conflict' if isinstance(error, RevisionConflict) else 'failed'
        fund.trade_enabled = False
        run.conflicts = error.conflicts if isinstance(error, RevisionConflict) else []
        run.message = str(error) if isinstance(error, SourceFailure) else '来源数据校验失败，已保留已有数据。'
    run.evidence = transport.evidence if transport else []
    run.finished_at = datetime.now(timezone.utc)
    result = {'fund_code': code, 'status': run.status, 'inserted': run.inserted or 0,
              'unchanged': run.unchanged or 0, 'message': run.message}
    db.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codes', nargs='+', choices=CODES, default=list(CODES))
    parser.add_argument('--full', action='store_true', help='Fetch all available historical pages, rather than recent/incremental history')
    args = parser.parse_args()
    failed = False
    for code in dict.fromkeys(args.codes):
        with Session(get_engine()) as db:
            result = synchronize(db, code, full=args.full)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            failed = failed or result['status'] != 'success'
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
