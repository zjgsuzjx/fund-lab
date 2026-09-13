import { useEffect, useState, type FormEvent } from 'react'
import { getJson, type FundPage, type Health } from './api'

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [data, setData] = useState<FundPage | null>(null)
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    Promise.all([
      getJson<Health>('/api/health/ready', controller.signal),
      getJson<FundPage>(`/api/funds?q=${encodeURIComponent(query)}&page_size=100`, controller.signal),
    ]).then(([status, funds]) => {
      if (!controller.signal.aborted) { setHealth(status); setData(funds) }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) {
        setHealth(null); setData(null)
        setError(reason instanceof Error && reason.name === 'Error' ? reason.message : '连接超时或后端未启动，请启动服务后重试。')
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [query, refresh])

  function search(event: FormEvent) {
    event.preventDefault()
    setQuery(input.trim())
    setRefresh(value => value + 1)
  }

  return <>
    <header className="header"><a className="brand" href="/"><span className="brand-icon">F</span>基金练习室<span className="brand-en">Fund Lab</span></a><span className="badge">本地开发版</span></header>
    <main>
      <section className="hero">
        <div><p className="eyebrow">从理解一只基金开始</p><h1>让每一次投资，<br />先成为一次练习。</h1><p className="intro">用虚拟资金理解基金投资的过程。<br />当前已接通基础服务，可浏览已验证的基金样本。</p></div>
        <div className="hero-note"><span className="note-icon">↗</span><strong>先了解，再行动</strong><p>基金以正式净值确认份额。<br />交易规则核验完成后，将开放模拟买卖。</p><span>仅供模拟练习 · 不涉及真实资金</span></div>
      </section>
      <section className="connection" aria-label="服务连接状态" aria-live="polite">
        <div><span className={`dot ${health && !loading ? 'online' : ''}`} />{loading ? '正在检查连接…' : health ? '本地服务已就绪' : '服务连接待恢复'}</div>
        <p>{health && !loading ? `数据库已连接 · 已载入 ${health.fund_count} 只基金` : '前端 · API · PostgreSQL'}</p>
        <button className="text-button" onClick={() => setRefresh(value => value + 1)} disabled={loading}>重新检查</button>
      </section>
      <section className="fund-section" aria-labelledby="fund-heading">
        <div className="section-top"><div><p className="eyebrow">探索基金</p><h2 id="fund-heading">从这些基金开始了解</h2></div><span className="badge">只读样本</span></div>
        <p className="muted">以下为 2026 年 9 月 13 日验证时保存的数据，非实时行情，也不代表支付宝当前在售清单。</p>
        <form className="search" onSubmit={search}><label className="sr-only" htmlFor="fund-search">基金名称或代码</label><input id="fund-search" value={input} onChange={event => setInput(event.target.value)} maxLength={100} placeholder="搜索基金名称或 6 位代码" /><button type="submit" disabled={loading}>搜索</button></form>
        {error && <div className="error" role="alert">{error}<button onClick={() => setRefresh(value => value + 1)}>重试</button></div>}
        {loading ? <p className="empty" role="status">正在加载基金…</p> : data && <>
          <div className="result-count" role="status">共 {data.total} 只基金</div>
          {data.items.length === 0 ? <div className="empty">{query ? '没有匹配的基金，试试名称或代码。' : '暂无基金数据。完成样本导入后，将在这里显示。'}</div> : <div className="fund-grid">{data.items.map(fund => <article className="fund-card" key={fund.code}>
            <div className="fund-type">{fund.category}</div><h3>{fund.name}</h3><p className="fund-code">{fund.code}</p>
            <div className="nav-row"><div><span>单位净值</span><strong>{fund.unit_nav ? Number(fund.unit_nav).toFixed(4) : '—'}</strong></div><time dateTime={fund.nav_date ?? undefined}>{fund.nav_date ?? '暂无净值'}</time></div>
            <div className="card-footer"><span>{fund.is_sample ? '历史验证样本' : '已同步数据'}</span><span>模拟交易待开放</span></div>
          </article>)}</div>}
        </>}
      </section>
      <footer>基金练习室是独立模拟项目，与支付宝及其关联公司无隶属或合作关系。<br />账户、持仓和交易功能正在开发中。</footer>
    </main>
  </>
}
