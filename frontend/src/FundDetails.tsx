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
  const [section, setSection] = useState('performance')
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
  const returnTo = /^(discover(?:\?|$)|holdings$|orders$)/.test(requestedReturn) ? requestedReturn : 'discover'
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
  return <main className="market-shell detail-page"><div className="detail-title"><a href={`#${returnTo}`} aria-label="返回上一页">‹</a><h1>基金详情</h1></div>
    {loading ? <section className="market-empty" role="status">正在加载基金详情…</section> : error ? <section className="market-empty"><p role="alert">{error}</p><button className="secondary" onClick={() => setRefresh(value => value + 1)}>重新加载</button><a href="#discover">返回发现页</a></section> : fund && <>
      <div className="detail-subtitle"><p>{fund.is_sample ? '历史验证样本' : '公开基金数据'} · {fund.code}</p><span className="fund-availability">{fund.trade_enabled ? '支持模拟买入' : '仅供查看'}</span></div>
      {watchError && <p role="alert" className="error">{watchError}</p>}
      <section className="detail-summary"><h2>{fund.name}</h2><div className="fund-tags"><span>{fund.category}</span><span>{fund.share_class ? `${fund.share_class} 类份额` : '份额类别暂无'}</span></div><div className="fund-key-metrics"><div><span>近一年净值涨跌</span><ChangeValue value={fund.year_change} /></div><div><span>单位净值</span><strong>{fund.unit_nav ? Number(fund.unit_nav).toFixed(4) : '—'}</strong><time>{fund.nav_date ?? '等待更新'}</time></div></div><p className="fund-metric-note">净值涨跌不含分红再投资，不代表持有收益。</p></section>
      <div className="detail-sections" role="group" aria-label="基金详情内容">{[['performance', '净值表现'], ['rules', '交易规则'], ['information', '基金资料']].map(([value, label]) => <button key={value} aria-pressed={section === value} onClick={() => setSection(value)}>{label}</button>)}</div>
      {section === 'performance' && <section className="chart-card"><div className="chart-heading"><h2>净值走势</h2><span>{fund.is_sample ? '历史样本' : '正式单位净值'}</span></div>{chartLoading ? <div className="chart-empty" role="status">正在加载净值…</div> : chartError ? <div className="chart-empty"><p role="alert">{chartError}</p><button onClick={() => setRefresh(value => value + 1)}>重新加载</button></div> : history && <NavChart data={history} />}
        <div className="period-tabs" role="group" aria-label="净值区间">{[['1m', '近1月'], ['3m', '近3月'], ['1y', '近1年'], ['all', '成立来']].map(([value, label]) => <button key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>{label}</button>)}</div>
        {history && <div className="chart-caption"><p>{history.message || `截至 ${history.end_date} · 区间单位净值涨跌`}{history.change !== null && <> <ChangeValue value={history.change} /></>}</p><small>区间按最新已公布净值日回溯。{history.basis}。</small></div>}
      </section>}
      {section === 'rules' && <section className="rules-card"><h2>交易规则</h2><p className="rules-status">{fund.trade_enabled ? '公开标准费率模拟方案 · 买入已开放' : '规则待核验或数据待更新 · 暂不可交易'}</p><p>起购金额：{fund.rules.minimum_purchase ?? '待核验'}</p><p className="rule-muted">确认时间：{fund.rules.confirmation ?? '待核验'} · 到账时间：{fund.rules.arrival ?? '待核验'}</p><details><summary>查看申购、赎回与持有期费用规则 ›</summary><p className="rule-note">{fund.rules.note}</p><FeeTable title="申购费率" rows={fund.rules.subscription_fees} unit="申购金额 M（元）" /><FeeTable title="赎回费率" rows={fund.rules.redemption_fees} unit="持有时间（天）" /><FeeTable title="持续费用" rows={fund.rules.ongoing_fees} unit="费用类型" /><p className="rule-note">持续费用通常已计入基金净值，不能作为额外交易手续费重复扣除。</p><p className="rule-note">{fund.rules.is_snapshot ? '历史验证快照' : '官网观察记录'} · {formatDate(fund.rules.observed_at)}<br />{fund.simulation_rule ? '下单采用已核验的模拟规则快照。' : '规则生效日期尚未核验。'}</p><a href={fund.rules.source_url} target="_blank" rel="noreferrer">查看基金公司费率来源 ↗</a></details></section>}
      {section === 'information' && <section className="source-card"><h2>数据来源</h2><p><a href={fund.source_url} target="_blank" rel="noreferrer">基金公司官网 ↗</a><a href={fund.nav_source_url} target="_blank" rel="noreferrer">公开净值来源 ↗</a></p><p>{fund.is_sample ? '历史样本观察' : '最近成功同步'}：{formatDate(fund.source_observed_at)}</p><p>已保存 {fund.history_count} 条净值 · {fund.earliest_nav_date ?? '暂无'} 起</p><p>{fund.history_complete ? '已获取来源全部历史页' : '历史尚未全部补齐'}；当前不提供分红复权总回报。</p></section>}
      <p className="data-disclosure">{fund.trade_disabled_reason}<br />仅供模拟练习，不发生真实交易。</p><div className="detail-action-bar"><button className="watch-action" aria-pressed={fund.is_watched} disabled={busy} onClick={() => void toggleWatch()}><img src="/assets/compass.svg" alt="" />{busy ? '保存中' : fund.is_watched ? '已自选' : '加自选'}</button><button className="primary" disabled={!fund.trade_enabled} onClick={() => { if (!user) onUnauthorized('请先登录后使用虚拟资金买入。'); else location.hash = `buy/${code}` }}>{fund.trade_enabled ? '模拟买入' : '模拟买入 · 暂不可用'}</button></div>
    </>}
  </main>
}
