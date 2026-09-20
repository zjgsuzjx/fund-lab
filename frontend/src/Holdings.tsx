import { useState } from 'react'
import type { Portfolio } from './api'
import { formatMoney } from './MarketShared'
import Dividends from './Dividends'
import './holdings.css'

export function Profit({ value, percent = false }: { value: string | null; percent?: boolean }) {
  return <strong className={`profit ${value === null ? 'missing' : Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : ''}`}>{value === null ? '—' : `${Number(value) > 0 ? '+' : ''}${formatMoney(value)}${percent ? '%' : ''}`}</strong>
}
const amount = (v: string | null) => v === null ? '—' : formatMoney(v)

export default function Holdings({ portfolio: p, refresh, onRefresh }: { portfolio: Portfolio; refresh: number; onRefresh: () => void }) {
  const [details, setDetails] = useState(false)
  return <>
    <header className="holdings-heading"><h1>持有</h1><button onClick={() => setDetails(!details)} aria-expanded={details} aria-controls="earnings-details">{details ? '收起明细' : '收益明细'}</button></header>
    <section className="earnings-card" aria-label="收益总览">
      <div className="latest-earning"><div><span>最新收益{p.earnings_date ? `（${p.earnings_date.slice(5)}）` : ''}</span><Profit value={p.latest_profit} /></div><small>{p.latest_profit === null ? '待更新' : '按正式净值计算'}</small></div>
      <div className="earnings-grid"><div><span>持有收益</span><Profit value={p.holding_profit} /></div><div><span>累计收益</span><Profit value={p.total_profit} /></div><div><span>持有收益率</span><Profit value={p.holding_return} percent /></div></div>
    </section>
    {details && <section className="earnings-details" id="earnings-details"><h2>收益明细</h2><p>{p.earnings_note}</p><p>持有收益是当前份额的市值减成本；累计收益还包含已卖出收益与现金分红。持有收益率按剩余成本计算。</p><div className="earnings-history">{p.earnings_history.length ? p.earnings_history.map(row => <div key={row.date}><time>{row.date}</time>{row.profit === null ? <span>待更新</span> : <Profit value={row.profit} />}</div>) : <p>确认首笔交易后，这里将显示最近 30 天的交易日收益。</p>}</div><p>{p.valuation_note}</p><Dividends refresh={refresh} /></section>}
    <a className="fund-asset-row" href="#account"><div><span>基金资产（元）</span><strong>{amount(p.market_value)}</strong></div><span>持有 {p.items.length} 只基金</span></a>
    {(Number(p.reserved_cash) > 0 || Number(p.redemption_cash) > 0) && <a className="pending-strip" href="#orders"><img src="/assets/clock-3.svg" width="22" height="22" alt="" />有交易待确认或到账<span>查看进度</span></a>}
    {Number(p.dividend_cash) > 0 && <button className="pending-strip dividend-strip" onClick={() => setDetails(true)}>现金红利待到账<span>{amount(p.dividend_cash)} 元 · 查看明细</span></button>}
    <div className="holdings-list-heading"><h2>我的持有</h2><button onClick={onRefresh}>刷新</button></div>
    {p.items.length === 0 ? <section className="market-empty"><h2>暂无已确认持有</h2><p>买入确认后，即可在这里查看基金与收益。</p><a href="#discover">去发现基金</a></section> : p.items.map(item => <article className="holding-card" key={item.fund_code}>
      <a className="holding-name" href={`#fund/${item.fund_code}`}><h2>{item.fund_name}</h2><span>{item.fund_code} · 净值日期 {item.nav_date ?? '待更新'}</span></a>
      <div className="holding-metrics"><div><span>持有金额</span><strong>{amount(item.market_value)}</strong></div><div><span>最新收益{p.earnings_date && <small className="metric-date">{p.earnings_date.slice(5)}</small>}</span><Profit value={item.latest_profit} /></div><div><span>持有收益</span><Profit value={item.holding_profit} /></div><div><span>持有收益率</span><Profit value={item.holding_return} percent /></div></div>
      <details className="position-details"><summary>份额与交易</summary><dl><dt>持有份额</dt><dd>{amount(item.shares)}</dd><dt>冻结份额</dt><dd>{amount(item.frozen_shares)}</dd><dt>可赎回份额</dt><dd>{amount(item.available_shares)}</dd><dt>剩余成本（含申购费）</dt><dd>{amount(item.cost)}</dd></dl><div className="position-actions"><a href={`#buy/${item.fund_code}`}>追加买入</a><a href={`#sell/${item.fund_code}`}>卖出份额</a></div>{item.sell_disabled_reason && <p>{item.sell_disabled_reason}</p>}<details><summary>确认批次</summary>{item.lots.map(lot => <a className="lot-link" key={lot.order_id} href={`#order/${lot.order_id}`}>{lot.confirmation_date} · {amount(lot.shares)} 份</a>)}</details></details>
    </article>)}
    <div className="holdings-links"><a href="#orders"><img src="/assets/notebook-pen.svg" width="22" height="22" alt="" />交易记录</a><a href="#account"><img src="/assets/chart-pie.svg" width="22" height="22" alt="" />资金详情</a></div>
    <p className="earnings-caption">{p.earnings_date ? `最新收益对应 ${p.earnings_date}，不代表盘中实时收益。` : '等待首笔交易确认及正式净值更新。'}<br />模拟投资 · 所有金额均为虚拟资金</p>
  </>
}
