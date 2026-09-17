import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type Account, type FundPage, type SyncRuns, type User } from './api'
import { MarketNavigation, formatMoney, formatDate, ChangeValue } from './MarketShared'

type Filters = { q: string; category: string; sort: string; watchlist: boolean; page: number }
function readFilters(): Filters {
  const params = new URLSearchParams(location.hash.split('?')[1] ?? '')
  const category = params.get('category') ?? 'all', sort = params.get('sort') ?? 'code'
  return { q: (params.get('q') ?? '').slice(0, 100),
    category: ['all', 'bond', 'index', 'mixed'].includes(category) ? category : 'all',
    sort: ['code', 'name', 'nav_desc', 'change_desc', 'change_asc'].includes(sort) ? sort : 'code',
    watchlist: params.get('watchlist') === 'true', page: Math.max(1, Math.min(100000, Number(params.get('page')) || 1)) }
}

export default function Discover({ user, onUnauthorized }: { user: User | null; onUnauthorized: (message: string) => void }) {
  const [filters, setFilters] = useState(readFilters)
  const [input, setInput] = useState(filters.q)
  const [data, setData] = useState<FundPage | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [accountError, setAccountError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [watchError, setWatchError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [pending, setPending] = useState<string | null>(null)
  const pendingRef = useRef(false)
  const [runs, setRuns] = useState<SyncRuns | null>(null)
  const [runsError, setRunsError] = useState('')
  const [showRuns, setShowRuns] = useState(false)
  const [runsLoading, setRunsLoading] = useState(false)
  useEffect(() => {
    const update = () => { const next = readFilters(); setFilters(next); setInput(next.q) }
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  function updateFilters(changes: Partial<Filters>) {
    const next = { ...filters, page: 1, ...changes }
    const params = new URLSearchParams({ q: next.q, category: next.category, sort: next.sort, watchlist: String(next.watchlist), page: String(next.page) })
    location.hash = `discover?${params}`
    setFilters(next)
  }
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setData(null)
    if (filters.watchlist && !user) { setLoading(false); return () => controller.abort() }
    const params = new URLSearchParams({ ...filters, page: String(filters.page), watchlist: String(filters.watchlist), page_size: '3' })
    api<FundPage>(`/funds?${params}`, undefined, controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result)
    }).catch(reason => {
      if (!controller.signal.aborted) {
        if (reason instanceof ApiError && reason.status === 401) onUnauthorized('请重新登录后查看自选。')
        else setError((reason as Error).message)
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [filters.q, filters.category, filters.sort, filters.watchlist, filters.page, refresh, user?.id])
  useEffect(() => {
    const controller = new AbortController()
    setAccount(null); setAccountError('')
    if (user) api<Account>('/account', undefined, controller.signal).then(value => { if (!controller.signal.aborted) setAccount(value) }).catch(reason => {
      if (!controller.signal.aborted) {
        if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。')
        else setAccountError((reason as Error).message)
      }
    })
    return () => controller.abort()
  }, [user?.id, refresh])
  useEffect(() => {
    if (!showRuns) return
    const controller = new AbortController()
    setRunsLoading(true); setRunsError('')
    api<SyncRuns>('/data/sync-runs', undefined, controller.signal).then(value => { if (!controller.signal.aborted) setRuns(value) }).catch(reason => {
      if (!controller.signal.aborted) setRunsError((reason as Error).message)
    }).finally(() => { if (!controller.signal.aborted) setRunsLoading(false) })
    return () => controller.abort()
  }, [showRuns, refresh])
  async function toggleWatch(code: string, enabled: boolean) {
    if (!user) { onUnauthorized('登录后即可保存自己的自选基金。'); return }
    if (pendingRef.current) return
    pendingRef.current = true; setPending(code); setWatchError('')
    try {
      await api(`/watchlist/${code}`, { enabled })
      setRefresh(value => value + 1)
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。')
      else setWatchError((reason as Error).message)
    } finally { pendingRef.current = false; setPending(null) }
  }
  function search(event: FormEvent) { event.preventDefault(); updateFilters({ q: input.trim() }) }
  return <main className="market-shell discover-page">
    <div className="market-title"><h1>基金练习室</h1><a href={user ? '#account' : '#login'}>{user ? '账户' : '登录'} ›</a></div><p className="subtitle">用虚拟资金，练习每一个投资决定</p>
    <section className="asset-card" aria-label="模拟资产"><span>模拟总资产（元）</span><strong className="asset-total">{account ? (account.total_assets === null ? '—' : formatMoney(account.total_assets)) : user ? '—' : '登录后查看'}</strong><div className="asset-columns"><div><span>买入在途</span><strong>{account ? formatMoney(account.reserved_cash) : '—'}</strong></div><div><span>可用余额</span><strong>{account ? formatMoney(account.available_cash) : '—'}</strong></div></div>{account && <small>总资产包含现金、买入在途与按已保存净值估算的持仓</small>}{accountError && <p role="alert">{accountError}<button onClick={() => setRefresh(value => value + 1)}>重试</button></p>}</section>
    <form className="market-search" onSubmit={search}><img src="/assets/search.svg" width="18" height="18" alt="" /><label className="sr-only" htmlFor="market-search">搜索基金名称或代码</label><input id="market-search" maxLength={100} value={input} onChange={event => setInput(event.target.value)} placeholder="搜索基金名称或代码" /><button type="submit">搜索</button></form>
    <div className="category-tabs" role="group" aria-label="基金分类">{[['all', '全部'], ['bond', '债券型'], ['index', '指数型'], ['mixed', '混合型']].map(([value, label]) => <button key={value} aria-pressed={filters.category === value} onClick={() => updateFilters({ category: value })}>{label}</button>)}</div>
    <div className="explore-heading"><h2>基金探索</h2><label className="sort-label"><span className="sr-only">基金排序</span><select aria-label="基金排序" value={filters.sort} onChange={event => updateFilters({ sort: event.target.value })}><option value="code">默认排序 · 代码</option><option value="name">基金名称</option><option value="change_desc">近一年净值涨幅 ↓</option><option value="change_asc">近一年净值涨幅 ↑</option><option value="nav_desc">单位净值 ↓</option></select></label></div>
    <div className="list-tools"><label><input type="checkbox" checked={filters.watchlist} onChange={event => updateFilters({ watchlist: event.target.checked })} />只看自选</label><span>{data ? `${data.total} 只基金` : '基金目录'}</span><button onClick={() => setRefresh(value => value + 1)} disabled={loading}>刷新数据</button></div>
    {watchError && <p role="alert" className="error">{watchError}</p>}
    {loading ? <section className="market-empty" role="status">正在加载基金…</section> : error ? <section className="market-empty"><p role="alert">{error}</p><button className="secondary" onClick={() => setRefresh(value => value + 1)}>重新加载</button></section> : filters.watchlist && !user ? <section className="market-empty"><h3>登录后，收藏你的关注</h3><p>自选基金会保存在你的独立账户中。</p><a className="secondary" href="#login">登录并查看自选</a></section> : data && <>
      <section className="fund-list" aria-label="基金列表">{data.items.map(fund => <article className="fund-list-row" key={fund.code}>
        <a className="fund-main-link" href={`#fund/${fund.code}?return=${encodeURIComponent(location.hash.slice(1) || 'discover')}`}><div><h3>{fund.name}</h3><p>{fund.category} · {fund.code}</p></div><div className="fund-change"><ChangeValue value={fund.year_change} /><small>近一年净值涨跌</small></div></a>
        <div className="fund-row-meta"><span>净值 {fund.unit_nav ? Number(fund.unit_nav).toFixed(4) : '暂无'} · {fund.nav_date ?? '日期暂无'}</span><button disabled={pending !== null} aria-pressed={fund.is_watched} aria-label={`${fund.is_watched ? '取消自选' : '加入自选'} ${fund.name}`} onClick={() => void toggleWatch(fund.code, !fund.is_watched)}>{pending === fund.code ? '保存中…' : fund.is_watched ? '已自选' : '+ 自选'}</button></div>
        <small className="fund-provenance">{fund.is_sample ? '历史验证样本' : '公开净值 · 本机缓存'} · {formatDate(fund.source_observed_at)} 更新</small>
      </article>)}{data.items.length === 0 && <div className="market-empty"><h3>{filters.watchlist && !filters.q && filters.category === 'all' ? '还没有自选基金' : '没有匹配的基金'}</h3><p>{filters.watchlist ? '试试调整筛选，或浏览全部基金添加自选。' : '试试其他名称、代码或分类。'}</p><button className="secondary" onClick={() => { setInput(''); updateFilters({ q: '', category: 'all', watchlist: false }) }}>查看全部基金</button></div>}</section>
      {data.total > 0 && <nav className="pagination" aria-label="分页"><button disabled={filters.page <= 1} onClick={() => updateFilters({ page: filters.page - 1 })}>上一页</button><span>第 {data.page} / {Math.max(1, Math.ceil(data.total / data.page_size))} 页</span><button disabled={filters.page * data.page_size >= data.total} onClick={() => updateFilters({ page: filters.page + 1 })}>下一页</button></nav>}
    </>}
    <p className="data-disclosure">公开基金数据，不代表支付宝在售清单。净值涨跌不含分红再投资；数据不足时显示“—”。</p>
    <aside className="soft-card"><strong>从理解交易规则开始</strong><p>净值、确认时间与费用，都会影响结果。<br />在基金详情中查看来源与费用说明。</p></aside>
    <details className="sync-details" open={showRuns} onToggle={event => setShowRuns(event.currentTarget.open)}><summary>数据更新记录</summary><p>页面读取本机已保存的数据；“刷新数据”重新读取缓存。同步由本机维护命令执行。</p>{runsLoading && <p role="status">正在读取更新记录…</p>}{runsError && <p role="alert">{runsError}<button onClick={() => setRefresh(value => value + 1)}>重试</button></p>}{runs?.items.length === 0 && <p>暂无在线同步记录，当前使用历史验证样本。</p>}{runs?.items.map(run => <div className="sync-row" key={run.id}><strong>{run.fund_code} · {run.status === 'success' ? '已更新' : run.status === 'conflict' ? '发现修订' : '更新失败'}</strong><time>{formatDate(run.finished_at ?? run.started_at)}</time><p>{run.message} 新增 {run.inserted} 条，已有 {run.unchanged} 条。</p></div>)}</details>
    <MarketNavigation active="discover" user={user} />
  </main>
}
