"""Bounded, read-only source probe. Standard library only; never executes remote JS.

Run: python -X utf8 scripts/verify_fund_sources.py
Raw responses stay in ignored .local/. Reports contain only small factual samples.
This verifies accessibility/consistency, NOT a production API or permission to trade.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CODES = ('000147', '000148', '110020', '007339', '110009', '110011')
DIRECTORY = 'https://fund.eastmoney.com/js/fundcode_search.js'
PAGE_SIZE = 20


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.stack = []
        self.cell = None
        self.row = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.stack.append({'attrs': dict(attrs), 'rows': []})
        elif self.stack and tag == 'tr':
            self.row = []
        elif self.stack and tag in ('td', 'th'):
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is not None:
                self.row.append(re.sub(r'\s+', ' ', ''.join(self.cell)).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None and self.stack:
            self.stack[-1]['rows'].append(self.row)
            self.row = None
        elif tag == 'table' and self.stack:
            self.tables.append(self.stack.pop())


def parse_directory(text):
    match = re.fullmatch(r'\s*var\s+r\s*=\s*(\[.*\])\s*;?\s*', text, re.S)
    if not match:
        raise ValueError('Unexpected directory envelope; JS execution is forbidden')
    rows = json.loads(match[1])
    result = {}
    for row in rows:
        if len(row) != 5 or not re.fullmatch(r'\d{6}', row[0]):
            raise ValueError('Unexpected directory row')
        if row[0] in result:
            raise ValueError('Duplicate fund code')
        result[row[0]] = dict(zip(('code', 'pinyin', 'name', 'type', 'full_pinyin'), row))
    return result


def positive_decimal(value):
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError('NAV must be finite and positive')
    return str(number)


def parse_history(text):
    payload = json.loads(text)
    if payload.get('ErrCode') not in (None, 0):
        raise ValueError('Upstream returned an error code')
    rows = []
    for item in payload['Data']['LSJZList']:
        day = date.fromisoformat(item['FSRQ'])
        if day > datetime.now(timezone.utc).date():
            raise ValueError('Future NAV date')
        rows.append({
            'date': day.isoformat(), 'unit_nav': positive_decimal(item['DWJZ']),
            'cumulative_nav': positive_decimal(item['LJJZ']) if item.get('LJJZ') not in (None, '', '--') else None,
            'historical_purchase_status': item.get('SGZT'),
            'historical_redemption_status': item.get('SHZT'),
            'dividend_note': item.get('FHFCZ') or None,
        })
    dates = [r['date'] for r in rows]
    if dates != sorted(set(dates), reverse=True):
        raise ValueError('Dates duplicate or out of descending order')
    return int(payload['TotalCount']), rows


def parse_official(text):
    parser = Tables()
    parser.feed(text)
    result = {'identity': {}, 'subscription_fees': [], 'redemption_fees': [],
              'ongoing_fees': [], 'nav_rows': [], 'dividend_rows': []}
    for table in parser.tables:
        rows = table['rows']
        if not rows:
            continue
        classes = table['attrs'].get('class', '').split()
        if 'baseinfo-table' in classes:
            result['identity'] = {r[0].rstrip(':：'): r[1] for r in rows if len(r) == 2 and r[0].rstrip(':：') in ('基金名称', '基金简称', '基金代码', '基金类型')}
        if 'table_feilv' in classes:
            if '申购费率' in rows[0]:
                result['subscription_fees'] = rows[1:]
            elif '赎回费率' in rows[0]:
                result['redemption_fees'] = rows[1:]
            elif rows[0][0] == '管理费':
                result['ongoing_fees'] = rows
        if rows[0][:2] == ['日期', '单位净值(元)']:
            result['nav_rows'] = [{'date': r[0], 'unit_nav': positive_decimal(r[1]), 'cumulative_nav': positive_decimal(r[3])} for r in rows[1:] if len(r) >= 4 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', r[0])]
        if rows[0][0] == '权益登记日':
            result['dividend_rows'] = rows[1:]
    # Restrict zero-fee detection to this fee section, not unrelated site text.
    section = re.search(r'<div class="content_title">申购费率</div>(.*?)<div class="content_title">赎回费率</div>', text, re.S)
    if section and '本基金不收取申购费' in section[1]:
        result['subscription_fees'] = [['不收取申购费', '0.00%']]
    return result


def parse_current_status(text):
    match = re.search(r'交易状态[：:]\s*</span>((?:\s*<span class="staticCell">.*?</span>){2})', text, re.S)
    if not match:
        return None
    values = re.findall(r'<span class="staticCell">(.*?)</span>', match[1], re.S)
    return [re.sub(r'<[^>]+>', '', value).strip() for value in values]


def compare_nav(official, history):
    by_date = {r['date']: r for r in history}
    compared, mismatches = 0, []
    for row in official:
        other = by_date.get(row['date'])
        if other is None:
            continue
        compared += 1
        if any(other[k] is None or Decimal(row[k]) != Decimal(other[k]) for k in ('unit_nav', 'cumulative_nav')):
            mismatches.append(row['date'])
    return {'overlapping_dates': compared, 'mismatches': mismatches,
            'passed': compared > 0 and not mismatches}


class Probe:
    def __init__(self, raw_dir, offline=False):
        self.raw_dir = raw_dir
        self.offline = offline
        self.evidence = []
        self.last_request = 0.0

    def get(self, key, url):
        file = self.raw_dir / (key + '.raw')
        meta_file = self.raw_dir / (key + '.json')
        if self.offline:
            raw = file.read_bytes()
            meta = json.loads(meta_file.read_text(encoding='utf-8'))
            if meta['url'] != url or hashlib.sha256(raw).hexdigest() != meta['sha256']:
                raise ValueError('Cache URL/hash mismatch')
        else:
            time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = Request(url, headers={'User-Agent': 'FundLab-SourceValidation/0.1', 'Referer': 'https://fundf10.eastmoney.com/', 'Accept': '*/*'})
            with urlopen(request, timeout=20) as response:
                raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise ValueError('Response size limit exceeded')
                meta = {'url': url, 'fetched_at_utc': datetime.now(timezone.utc).isoformat(), 'status': response.status,
                        'content_type': response.headers.get('Content-Type'), 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest()}
            file.write_bytes(raw)
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        self.evidence.append(meta)
        return raw.decode('utf-8-sig')  # Fail on invalid bytes; never silently replace.


def run(probe):
    directory = parse_directory(probe.get('directory', DIRECTORY))
    report = {'schema_version': 1, 'run_at_utc': datetime.now(timezone.utc).isoformat(), 'offline': probe.offline,
              'directory_count': len(directory), 'alipay_coverage': 'not_verified', 'funds': [], 'errors': []}
    for code in CODES:
        try:
            entry = directory[code]
            official_url = f'https://www.efunds.com.cn/fund/{code}.shtml'
            profile_url = f'https://fund.eastmoney.com/{code}.html'
            official = parse_official(probe.get(f'official-{code}', official_url))
            current = parse_current_status(probe.get(f'profile-{code}', profile_url))
            def history(page):
                url = 'https://api.fund.eastmoney.com/f10/lsjz?' + urlencode({'fundCode': code, 'pageIndex': page, 'pageSize': PAGE_SIZE})
                return parse_history(probe.get(f'history-{code}-{page}', url))
            total, first = history(1)
            total2, second = history(2)
            last_page = math.ceil(total / PAGE_SIZE)
            total3, last = history(last_page)
            newest = first + second
            dates = [r['date'] for r in newest]
            unique = dates == sorted(set(dates), reverse=True)
            crosscheck = compare_nav(official['nav_rows'], newest)
            excluded = 'QDII' in (entry['type'] + entry['name']).upper()
            item = {'code': code, 'name': entry['name'], 'directory_type': entry['type'],
                    'official_identity': official['identity'], 'sources': {'official': official_url, 'profile': profile_url},
                    'declared_history_count': total, 'pages_probed': [1, 2, last_page],
                    'history_rows_probed': len(first) + len(second) + len(last),
                    'pagination_passed': total == total2 == total3 and unique and len(first) == PAGE_SIZE and len(second) == PAGE_SIZE and bool(last) and newest[-1]['date'] > last[0]['date'],
                    'full_history_continuity_verified': False, 'latest': first[0], 'oldest_sample_date': last[-1]['date'],
                    'nav_crosscheck': crosscheck, 'latest_samples': first[:3],
                    'current_profile_status': current,
                    'status_fields_disagree': bool(current) and current[0] != first[0]['historical_purchase_status'],
                    'standard_subscription_fee_rows': official['subscription_fees'],
                    'standard_redemption_fee_rows': official['redemption_fees'],
                    'ongoing_fee_rows': official['ongoing_fees'],
                    'dividend_table_rows_visible': len(official['dividend_rows']),
                    'dividend_sample': official['dividend_rows'][:1],
                    'classification': 'exclude_qdii' if excluded else 'candidate_not_trade_enabled',
                    'trade_enabled': False,
                    'unverified': ['alipay_listing_and_channel_discount', 'channel_specific_live_trade_status',
                                   'minimum_amount_and_residual_shares', 'effective_dated_contract_rules',
                                   'confirmation_and_arrival_calendar', 'complete_corporate_actions', 'commercial_data_permission_and_sla']}
            if official['identity'].get('基金代码') != code:
                raise ValueError('Official fund code mismatch')
            if not official['subscription_fees'] or not official['redemption_fees']:
                raise ValueError('Official fee table missing')
            report['funds'].append(item)
            print(f'{code}: NAV overlap={crosscheck["overlapping_dates"]}, match={crosscheck["passed"]}, history={total}, status_disagreement={item["status_fields_disagree"]}', flush=True)
        except (ValueError, KeyError, IndexError, TypeError, OSError, InvalidOperation) as exc:
            report['errors'].append({'code': code, 'error': f'{type(exc).__name__}: {exc}'})
            print(f'{code}: FAILED {type(exc).__name__}', flush=True)
    report['evidence'] = probe.evidence
    report['technical_probe_passed'] = len(report['funds']) == len(CODES) and not report['errors'] and all(f['nav_crosscheck']['passed'] and f['pagination_passed'] for f in report['funds'])
    report['production_trade_ready'] = False
    return report


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Replay captured local responses without network access')
    parser.add_argument('--raw-dir', type=Path, default=ROOT / '.local/fund-source-validation/probe')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/fund-source-validation/report.json')
    args = parser.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run(Probe(args.raw_dir, args.offline))
    except (ValueError, OSError) as exc:
        report = {'technical_probe_passed': False, 'production_trade_ready': False, 'errors': [f'{type(exc).__name__}: {exc}']}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Report: {args.output}')
    return 0 if report['technical_probe_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
