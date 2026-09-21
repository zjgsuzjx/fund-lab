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
    'version': '000147-public-standard-sim-v2', 'fund_code': '000147',
    'name': '公开标准费率模拟方案', 'observed_on': '2026-09-14',
    'simulation_from': '2026-09-14', 'simulation_through': '9999-12-31',
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
def utcnow():
    return datetime.now(timezone.utc)


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def trading_day(day):
    from .trading_calendar import is_trading_day
    return is_trading_day(day)


def next_trading_day(day):
    day += timedelta(days=1)
    while not trading_day(day):
        day += timedelta(days=1)
    return day


def schedule(now, rule=RULE):
    local = now.astimezone(CN)
    day = local.date()
    if not trading_day(day) or local.time() >= time(15):
        day = next_trading_day(day)
    confirmation = day
    for _ in range(rule['confirmation_days']):
        confirmation = next_trading_day(confirmation)
    return day, confirmation, datetime.combine(day, time(15), CN)


def fees(amount, rule=RULE):
    tier = next(t for t in rule['fee_tiers'] if t['below'] is None or amount < Decimal(t['below']))
    net = rounded(amount - Decimal(tier['fixed']) if 'fixed' in tier else amount / (1 + Decimal(tier['rate'])))
    return amount - net, net, tier


def disabled_reason(fund, now=None):
    now = now or utcnow()
    if not fund:
        return '尚未启用已核验的模拟买入方案。'
    rule = rule_for(fund)
    if not rule:
        return '该产品需要专用交易或收益模型，目前仅支持目录展示。'
    if not fund.trade_enabled:
        return '尚未启用模拟买入方案，请先成功同步基金数据。'
    if fund.is_sample or not fund.last_sync_at or now - fund.last_sync_at > timedelta(days=7):
        return '净值数据尚未同步或已超过 7 天，请先完成数据同步。'
    if not rule['simulation_from'] <= now.astimezone(CN).date().isoformat() <= rule['simulation_through']:
        return '模拟规则版本不覆盖当前日期，等待核验新版本。'
    try:
        schedule(now, rule)
    except HTTPException as exc:
        return exc.detail
    return ''


def rule_snapshot(fund=None):
    return rule_for(fund) if fund else deepcopy(RULE)


SELL_RULE = {
    'version': '000147-redemption-sim-v2', 'fund_code': '000147',
    'name': '公开标准赎回费率模拟方案', 'minimum': '0.01',
    'simulation_from': '2026-09-17', 'simulation_through': '9999-12-31',
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


def redemption_schedule(now, rule=SELL_RULE):
    trade, confirmation, cutoff = schedule(now, {**rule, 'confirmation_days': rule.get('confirmation_days', 1)})
    arrival = trade
    for _ in range(rule['arrival_days']):
        arrival = next_trading_day(arrival)
    return trade, confirmation, cutoff, arrival


def rule_for(fund, *, sell=False):
    """Independent immutable snapshots; generic fees are simulator assumptions."""
    if fund.code == (SELL_RULE if sell else RULE)['fund_code']:
        return deepcopy(SELL_RULE if sell else RULE)
    label = (fund.name + fund.category).upper()
    if any(term in label for term in ('QDII', '货币', '理财', 'REIT', 'FOF', '定开', '定期开放', '持有', '封闭', '养老', '美元', '港股', '香港')):
        return None
    if 'ETF' in label and '联接' not in label:
        return None
    if not any(term in fund.category for term in ('债券', '混合', '股票', '指数')):
        return None
    rule = deepcopy(SELL_RULE if sell else RULE)
    rule.update(version=f'{fund.code}-generic-{"sell" if sell else "buy"}-v1', fund_code=fund.code,
                name='通用练习费率（非基金实际费率）', simulation_from='2025-01-01',
                simulation_through='9999-12-31', confirmation_days=1,
                sources=[{'url': 'https://www.sse.com.cn/disclosure/dealinstruc/closed/'}],
                scope='通用模拟假设：1 元起购，申购费固定为 0；赎回持有不足 7 天收取 1.5%，满 7 天为 0。'
                      '按境内交易日 15:00 截止、T+1 起等待正式净值确认、赎回 T+7 到账。'
                      '不代表该基金合同、支付宝费率、实时限购或实际到账时间；未核验分红/拆分暂停赎回。')
    rule['fee_tiers'] = ([{'below_days': 7, 'rate': '0.015'}, {'below_days': None, 'rate': '0'}] if sell
                         else [{'below': None, 'rate': '0'}])
    return rule
