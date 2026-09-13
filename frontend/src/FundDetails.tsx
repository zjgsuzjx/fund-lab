import { useEffect, useRef, useState } from 'react'
import { api, ApiError, type FundDetail, type NavHistory, type User } from './api'
import { ChangeValue, formatDate } from './MarketShared'
import NavChart from './NavChart'

function FeeTable({ title, rows, unit }: { title: string; rows: string[][]; unit: string }) {
  return <section className="fee-section"><h3>{title}</h3>{rows.length ? <table><thead><tr><th>{unit}</th><th>标准费率 / 费用</th></tr></thead><tbody>{rows.map((row, index) => <tr key={index}><td>{row[0]}</td><td>{row.slice(1).join(' · ')}</td></tr>)}</tbody></table> : <p>暂无已核验信息</p>}</section>
}

export default function FundDetails({ code, user, onUnauthorized }: { code: string; user: User | null; onUnauthorized: (message: string) => void }) {
  const [fund, setFund] = useState<FundDetail | null>(null)
  const [period, setPeriod] = useState('1y')
  const [history, setHistory] = useState<NavHistory | null>(null)
  const [error, setError] = useState('')
  const [chartError, setChartError] = useState('')
  const [watchError, setWatchError] = useState('')
  const [loading, setLoading] = useState(true)
  const [chartLoading, setChartLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [refresh, setRefresh] = useState(0)
  const requestedReturn = new URLSearchParams(location.hash.split('?')[1] ?? '').get('return') ?? 'discover'
  const returnTo = /^discover(?:\?|$)/.test(requestedReturn) ? requestedReturn : 'discover'
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setFund(null)
    api<FundDetail>(`/funds/${encodeURIComponent(code)}`, undefined, controller.signal).then(value => {
      if (!controller.signal.aborted) setFund(value)
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [code, refresh, user?.id])
  useEffect(() => {
    const controller = new AbortController()
    setChartLoading(true); setChartError(''); setHistory(null)
    api<NavHistory>(`/funds/${encodeURIComponent(code)}/nav?period=${period}`, undefined, controller.signal).then(value => {
      if (!controller.signal.aborted) setHistory(value)
    }).catch(reason => { if (!controller.signal.aborted) setChartError((reason as Error).message) }).finally(() => { if (!controller.signal.aborted) setChartLoading(false) })
    return () => controller.abort()
  }, [code, period, refresh])
  async function toggleWatch() {
    if (!user) { onUnauthorized('登录后即可保存自己的自选基金。'); return }
    if (!fund || pending.current) return
    const enabled = !fund.is_watched
    pending.current = true; setBusy(true); setWatchError('')
    try { await api(`/watchlist/${code}`, { enabled }); setFund(current => current ? { ...current, is_watched: enabled } : null) }
    catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。')
      else setWatchError((reason as Error).message)
    } finally { pending.current = false; setBusy(false) }
  }
  return <main className="market-shell detail-page"><p className="account-tag">模拟账户</p><div className="detail-title"><a href={`#${returnTo}`} aria-label="返回基金发现">‹</a><h1>基金详情</h1></div>
    {loading ? <section className="market-empty" role="status">正在加载基金详情…</section> : error ? <section className="market-empty"><p role="alert">{error}</p><button className="secondary" onClick={() => setRefresh(value => value + 1)}>重新加载</button><a href="#discover">返回发现页</a></section> : fund && <>
      <div className="detail-subtitle"><p>{fund.is_sample ? '历史验证样本' : '公开基金数据'} · {fund.code}</p><button className="watch-button" aria-pressed={fund.is_watched} disabled={busy} onClick={() => void toggleWatch()}>{busy ? '保存中…' : fund.is_watched ? '已加入自选' : '+ 加入自选'}</button></div>
      {watchError && <p role="alert" className="error">{watchError}</p>}
      <section className="detail-summary"><h2>{fund.name}</h2><div className="fund-tags"><span>{fund.category}</span><span>{fund.share_class ? `${fund.share_class} 类份额` : '份额类别暂无'}</span></div><div className="detail-change"><ChangeValue value={fund.year_change} /><p>近一年单位净值涨跌</p><small>不含分红再投资，不代表投资总回报</small></div><div className="detail-nav-value"><span>单位净值 <strong>{fund.unit_nav ? Number(fund.unit_nav).toFixed(4) : '暂无'}</strong></span><time>{fund.nav_date ?? '暂无日期'}</time></div></section>
      <section className="chart-card"><div className="chart-heading"><h2>净值走势</h2><span>{fund.is_sample ? '历史样本' : '正式单位净值'}</span></div>{chartLoading ? <div className="chart-empty" role="status">正在加载净值…</div> : chartError ? <div className="chart-empty"><p role="alert">{chartError}</p><button onClick={() => setRefresh(value => value + 1)}>重新加载</button></div> : history && <NavChart data={history} />}
        <div className="period-tabs" role="group" aria-label="净值区间">{[['1m', '近1月'], ['3m', '近3月'], ['1y', '近1年'], ['all', '成立来']].map(([value, label]) => <button key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>{label}</button>)}</div>
        {history && <div className="chart-caption"><p>{history.message || `截至 ${history.end_date} · 区间单位净值涨跌`}{history.change !== null && <> <ChangeValue value={history.change} /></>}</p><small>区间按最新已公布净值日回溯。{history.basis}。</small></div>}
      </section>
      <section className="rules-card"><h2>交易规则</h2><p className="rules-status">规则待核验 · 暂不可交易</p><p>起购金额：{fund.rules.minimum_purchase ?? '待核验'}</p><p className="rule-muted">确认时间：{fund.rules.confirmation ?? '待核验'} · 到账时间：{fund.rules.arrival ?? '待核验'}</p><details><summary>查看申购、赎回与持有期费用规则 ›</summary><p className="rule-note">{fund.rules.note}</p><FeeTable title="申购费率" rows={fund.rules.subscription_fees} unit="申购金额 M（元）" /><FeeTable title="赎回费率" rows={fund.rules.redemption_fees} unit="持有时间（天）" /><FeeTable title="持续费用" rows={fund.rules.ongoing_fees} unit="费用类型" /><p className="rule-note">持续费用通常已计入基金净值，不能作为额外交易手续费重复扣除。</p><p className="rule-note">{fund.rules.is_snapshot ? '历史验证快照' : '官网观察记录'} · {formatDate(fund.rules.observed_at)}<br />规则生效日期尚未核验。</p><a href={fund.rules.source_url} target="_blank" rel="noreferrer">查看基金公司费率来源 ↗</a></details></section>
      <section className="source-card"><h2>数据来源</h2><p><a href={fund.source_url} target="_blank" rel="noreferrer">基金公司官网 ↗</a><a href={fund.nav_source_url} target="_blank" rel="noreferrer">公开净值来源 ↗</a></p><p>{fund.is_sample ? '历史样本观察' : '最近成功同步'}：{formatDate(fund.source_observed_at)}</p><p>已保存 {fund.history_count} 条净值 · {fund.earliest_nav_date ?? '暂无'} 起</p><p>{fund.history_complete ? '已获取来源全部历史页' : '历史尚未全部补齐'}；当前不提供分红复权总回报。</p></section>
      <p className="data-disclosure">{fund.trade_disabled_reason}<br />仅供模拟练习，不发生真实交易。</p><button className="primary buy-disabled" disabled>模拟买入 · 暂未开放</button><p className="detail-footer">了解规则，再做决定</p>
    </>}
  </main>
}
