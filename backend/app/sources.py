"""Strict public-source parsers shared by the probe and application sync. Never execute source JavaScript."""
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser

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
