"""Published SSE calendars, atomically cached. Never invent next year's holidays."""
import json
import re
from functools import lru_cache
from datetime import date
from html import unescape

from fastapi import HTTPException

from .config import ROOT

SOURCE = 'https://www.sse.com.cn/disclosure/dealinstruc/closed/'
CACHE = ROOT / 'data' / 'calendars'
BUILTIN = {
    2025: [('2025-01-01', '2025-01-01'), ('2025-01-28', '2025-02-04'),
           ('2025-04-04', '2025-04-06'), ('2025-05-01', '2025-05-05'),
           ('2025-05-31', '2025-06-02'), ('2025-10-01', '2025-10-08')],
    2026: [('2026-01-01', '2026-01-03'), ('2026-02-15', '2026-02-23'),
           ('2026-04-04', '2026-04-06'), ('2026-05-01', '2026-05-05'),
           ('2026-06-19', '2026-06-21'), ('2026-09-25', '2026-09-27'),
           ('2026-10-01', '2026-10-07')],
}


def validate(year, ranges):
    if not 6 <= len(ranges) <= 7:
        raise ValueError('年度休市安排不完整。')
    previous = None
    for start, end in ranges:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a.year != year or b.year != year or not 0 <= (b - a).days <= 15 or (previous and a <= previous):
            raise ValueError('年度休市日期异常。')
        previous = b
    return ranges


@lru_cache(maxsize=32)
def read_calendar(path, year, modified):
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload['year'] != year or payload['source'] != SOURCE:
        raise ValueError('日历来源异常')
    return validate(year, payload['ranges'])


def holiday_ranges(year):
    path = CACHE / f'{year}.json'
    try:
        if path.exists():
            return read_calendar(path, year, path.stat().st_mtime_ns)
    except (ValueError, KeyError, TypeError, OSError):
        raise HTTPException(409, f'{year} 年交易日历缓存异常，请重新同步。')
    if year in BUILTIN:
        return BUILTIN[year]
    raise HTTPException(409, f'{year} 年交易日历尚未发布或同步，请更新日历后重试。')


def is_trading_day(day):
    ranges = holiday_ranges(day.year)
    return day.weekday() < 5 and not any(a <= day.isoformat() <= b for a, b in ranges)


def parse_calendar(html):
    text = re.sub(r'\s+', '', unescape(re.sub(r'<[^>]+>', '', html)))
    section = re.search(r'(20\d{2})年休市安排(.*?)(?:相关公告|关于上海证券交易所)', text)
    if not section:
        raise ValueError('无法识别交易所年度日历。')
    year, body = int(section[1]), section[2]
    holidays = ('元旦', '春节', '清明节', '劳动节', '端午节', '中秋节', '国庆节')
    if not all(name in body for name in holidays):
        raise ValueError('交易所年度日历缺少节假日。')
    pattern = r'(\d{1,2})月(\d{1,2})日（[^）]+）(?:至(?:(\d{1,2})月)?(\d{1,2})日（[^）]+）)?休市'
    ranges = []
    for m, d, em, ed in re.findall(pattern, body):
        start = date(year, int(m), int(d))
        end = date(year, int(em or m), int(ed or d))
        ranges.append((start.isoformat(), end.isoformat()))
    return year, validate(year, sorted(set(ranges)))


def sync_calendar(transport):
    year, ranges = parse_calendar(transport.get(SOURCE))
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f'{year}.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'year': year, 'ranges': ranges, 'source': SOURCE}, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)
    return year
