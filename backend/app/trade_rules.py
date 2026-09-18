"""Versioned Fund Lab simulation policy; never a live distributor's trading promise.

Public contract facts and the simulator's scheduling choices are separated in
RULE. Existing orders keep this entire snapshot even if a later version changes.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

CN = timezone(timedelta(hours=8))
CENT = Decimal('0.01')
PROSPECTUS = 'https://cdn.efunds.com.cn/owch/data/bulletin/20260131/易方达高等级信用债债券型证券投资基金更新的招募说明书.pdf'
CALENDAR_SOURCE = 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml'
RULE = {
    'version': '000147-public-standard-sim-v1', 'fund_code': '000147',
    'name': '公开标准费率模拟方案', 'observed_on': '2026-09-14',
    'simulation_from': '2026-09-14', 'simulation_through': '2026-12-31',
    'minimum': '1.00', 'rounding': 'ROUND_HALF_UP', 'money_decimals': 2, 'share_decimals': 2,
    'fee_tiers': [{'below': '1000000', 'rate': '0.008'}, {'below': '2000000', 'rate': '0.005'},
                  {'below': '5000000', 'rate': '0.003'}, {'below': None, 'fixed': '1000.00'}],
    'confirmation_days': 1, 'timezone': 'Asia/Shanghai', 'cutoff': '15:00',
    'sources': [{'url': PROSPECTUS, 'pages': '26–31', 'published_on': '2026-01-31'},
                {'url': CALENDAR_SOURCE, 'published_on': '2025-12-22'}],
    'scope': '采用招募说明书普通投资者标准费率、1 元起购和金额/份额两位四舍五入。'
             '本练习室约定交易日 15:00 截止，非交易时间顺延，截止前可撤单；'
             'T+1 起且正式 T 日净值已同步后确认。不模拟渠道折扣、实时限购或临时停牌公告，'
             '不代表支付宝或其他销售渠道当前可购买状态。',
}
HOLIDAY_RANGES = [('2026-01-01', '2026-01-03'), ('2026-02-15', '2026-02-23'),
                  ('2026-04-04', '2026-04-06'), ('2026-05-01', '2026-05-05'),
                  ('2026-06-19', '2026-06-21'), ('2026-09-25', '2026-09-27'),
                  ('2026-10-01', '2026-10-07')]


def utcnow():
    return datetime.now(timezone.utc)


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def trading_day(day):
    if day.year != 2026:
        raise HTTPException(409, '该日期的交易日历尚未核验，暂不能提交。')
    return day.weekday() < 5 and not any(start <= day.isoformat() <= end for start, end in HOLIDAY_RANGES)


def next_trading_day(day):
    day += timedelta(days=1)
    while not trading_day(day):
        day += timedelta(days=1)
    return day


def schedule(now):
    local = now.astimezone(CN)
    day = local.date()
    if not trading_day(day) or local.time() >= time(15):
        day = next_trading_day(day)
    return day, next_trading_day(day), datetime.combine(day, time(15), CN)


def fees(amount, rule=RULE):
    tier = next(t for t in rule['fee_tiers'] if t['below'] is None or amount < Decimal(t['below']))
    net = rounded(amount - Decimal(tier['fixed']) if 'fixed' in tier else amount / (1 + Decimal(tier['rate'])))
    return amount - net, net, tier


def disabled_reason(fund, now=None):
    now = now or utcnow()
    if not fund or fund.code != RULE['fund_code'] or not fund.trade_enabled:
        return '尚未启用已核验的模拟买入方案。'
    if fund.is_sample or not fund.last_sync_at or now - fund.last_sync_at > timedelta(days=7):
        return '净值数据尚未同步或已超过 7 天，请先完成数据同步。'
    if not RULE['simulation_from'] <= now.astimezone(CN).date().isoformat() <= RULE['simulation_through']:
        return '模拟规则版本不覆盖当前日期，等待核验新版本。'
    try:
        schedule(now)
    except HTTPException as exc:
        return exc.detail
    return ''


def rule_snapshot():
    return deepcopy(RULE)


SELL_RULE = {
    'version': '000147-redemption-sim-v1', 'fund_code': '000147',
    'name': '公开标准赎回费率模拟方案', 'minimum': '0.01',
    'simulation_from': '2026-09-17', 'simulation_through': '2026-12-31',
    'rounding': 'ROUND_HALF_UP', 'allocation': 'FIFO', 'arrival_days': 7,
    'fee_tiers': [{'below_days': 7, 'rate': '0.015'}, {'below_days': 30, 'rate': '0.0075'},
                  {'below_days': 365, 'rate': '0.001'}, {'below_days': 730, 'rate': '0.0005'},
                  {'below_days': None, 'rate': '0'}],
    'sources': [{'url': PROSPECTUS, 'pages': '3–4、26–32', 'published_on': '2026-01-31'},
                {'url': CALENDAR_SOURCE, 'published_on': '2025-12-22'}],
    'scope': '0.01 份起赎，按先确认先赎回分配批次，持有天数从买入确认日算至赎回确认日（不含）。'
             '本练习室约定 15:00 截止、截止前可撤单；T+1 起按正式 T 日净值确认，T+7 到账。'
             'T+n 为交易日，持有天数为自然日。招募说明书规定通常 T+7 内支付，'
             '此处 T+7 是模拟约定，不代表支付宝实际到账时间。未处理的分红/拆分事件会暂停赎回。',
}


def redemption_rate(days, rule=SELL_RULE):
    if days < 0:
        raise HTTPException(409, '持仓确认日期异常，请核验。')
    return Decimal(next(t['rate'] for t in rule['fee_tiers'] if t['below_days'] is None or days < t['below_days']))


def redemption_schedule(now):
    trade, confirmation, cutoff = schedule(now)
    arrival = trade
    for _ in range(SELL_RULE['arrival_days']):
        arrival = next_trading_day(arrival)
    return trade, confirmation, cutoff, arrival
