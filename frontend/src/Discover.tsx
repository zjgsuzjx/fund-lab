import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type Portfolio, type FundPage, type User } from './api'
import { MarketNavigation, formatDate, ChangeValue } from './MarketShared'
import SortMenu from './SortMenu'
import { Profit } from './Holdings'

type Filters = { q: string; category: string; sort: string; watchlist: boolean; page: number }
function readFilters(): Filters {
  const params = new URLSearchParams(location.hash.split('?')[1] ?? '')
  const category = params.get('category') ?? 'all', sort = params.get('sort') ?? 'change_desc'
  return {
    q: (params.get('q') ?? '').slice(0, 100),
    category: ['all', 'bond', 'index', 'mixed'].includes(category) ? category : 'all',
    sort: ['code', 'name', 'nav_desc', 'change_desc', 'change_asc'].includes(sort) ? sort : 'change_desc',
    watchlist: params.get('watchlist') === 'true', page: Math.max(1, Math.min(100000, Number(params.get('page')) || 1))
  }
}

export default function Discover({ user, onUnauthorized }: { user: User | null; onUnauthorized: (message: string) => void }) {
  const [filters, setFilters] = useState(readFilters)
  const [input, setInput] = useState(filters.q)
  const [data, setData] = useState<FundPage | null>(null)
  const [account, setAccount] = useState<Portfolio | null>(null)
  const [accountError, setAccountError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [watchError, setWatchError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [pending, setPending] = useState<string | null>(null)
  const pendingRef = useRef(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [moreError, setMoreError] = useState('')
  const [batches, setBatches] = useState(0)
  const sentinel = useRef<HTMLDivElement>(null)
  const explore = useRef<HTMLDivElement>(null)
  const loadMore = useRef<() => void>(() => {})
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
    let busy = false, batch = 0
    setLoading(true); setError(''); setData(null); setBatches(0); setMoreError(''); setLoadingMore(false)
    loadMore.current = () => {}
    if (filters.watchlist && !user) { setLoading(false); return () => controller.abort() }
    const load = async () => {
      if (busy || batch >= 5 || controller.signal.aborted) return
      busy = true
      const first = batch === 0
      if (!first) { setLoadingMore(true); setMoreError('') }
      const params = new URLSearchParams({ ...filters, page: String((filters.page - 1) * 5 + batch + 1), watchlist: String(filters.watchlist), page_size: '10' })
      try {
        const result = await api<FundPage>(`/funds?${params}`, undefined, controller.signal)
        if (controller.signal.aborted) return
        batch += 1
        setBatches(batch)
        setData(previous => first || !previous ? result : { ...result, items: [...previous.items, ...result.items.filter(item => !previous.items.some(old => old.code === item.code))] })
        if (result.items.length < 10 || (filters.page - 1) * 50 + batch * 10 >= result.total) batch = 5
      } catch (reason) {
        if (!controller.signal.aborted) {
          if (reason instanceof ApiError && reason.status === 401) onUnauthorized('请重新登录后查看自选。')
          else (first ? setError : setMoreError)((reason as Error).message)
        }
      } finally {
        busy = false
        if (!controller.signal.aborted) { setLoading(false); setLoadingMore(false) }
      }
    }
    loadMore.current = () => { void load() }
    void load()
    return () => controller.abort()
  }, [filters.q, filters.category, filters.sort, filters.watchlist, filters.page, refresh, user?.id])
  const hasMore = !!data && batches < 5 && (filters.page - 1) * 50 + batches * 10 < data.total
  useEffect(() => {
    if (!hasMore || loading || loadingMore || moreError || !sentinel.current) return
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) loadMore.current()
    }, { rootMargin: '120px' })
    observer.observe(sentinel.current)
    return () => observer.disconnect()
  }, [hasMore, loading, loadingMore, moreError, batches])
  function changePage(page: number) {
    updateFilters({ page })
    explore.current?.scrollIntoView({ block: 'start' })
  }
  useEffect(() => {
    const controller = new AbortController()
    setAccount(null); setAccountError('')
    if (user) api<Portfolio>('/holdings', undefined, controller.signal).then(value => { if (!controller.signal.aborted) setAccount(value) }).catch(reason => {
      if (!controller.signal.aborted) {
        if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。')
        else setAccountError((reason as Error).message)
      }
    })
    return () => controller.abort()
  }, [user?.id, refresh])
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
    <div className="market-title"><h1>基金练习室</h1><a href={user ? '#account' : '#login'}>{user ? '账户' : '登录'} ›</a></div><p className="subtitle">关注基金表现，记录每一份收益</p>
    <section className="discover-returns" aria-label="我的基金收益"><div className="market-title"><h2>我的收益</h2><a href={user ? '#holdings' : '#login'}>{user ? '查看持有' : '登录查看'}</a></div><div className="discover-profit-grid"><div><span>最新收益{account?.earnings_date ? `（${account.earnings_date.slice(5)}）` : ''}</span><Profit value={account?.latest_profit ?? null} /></div><div><span>累计收益</span><Profit value={account?.total_profit ?? null} /></div></div>{accountError && <p role="alert">{accountError}<button onClick={() => setRefresh(value => value + 1)}>重试</button></p>}</section>
    <nav className="discover-shortcuts" aria-label="基金快捷入口"><a href="#discover?watchlist=true"><img src="/assets/compass.svg" alt="" /><span>我的自选</span></a><a href={user ? '#holdings' : '#login'}><img src="/assets/chart-pie.svg" alt="" /><span>我的持有</span></a><a href={user ? '#orders' : '#login'}><img src="/assets/clock-3.svg" alt="" /><span>交易进度</span></a></nav>
    <form className="market-search" onSubmit={search}><img src="/assets/search.svg" width="18" height="18" alt="" /><label className="sr-only" htmlFor="market-search">搜索基金名称或代码</label><input id="market-search" maxLength={100} value={input} onChange={event => setInput(event.target.value)} placeholder="搜索基金名称或代码" /><button type="submit">搜索</button></form>
    <div className="category-tabs" role="group" aria-label="基金分类">{[['all', '全部'], ['bond', '债券型'], ['index', '指数型'], ['mixed', '混合型']].map(([value, label]) => <button key={value} aria-pressed={filters.category === value} onClick={() => updateFilters({ category: value })}>{label}</button>)}</div>
    <div className="explore-heading" ref={explore}><h2>基金探索</h2><SortMenu value={filters.sort} onChange={sort => updateFilters({ sort })} /></div>
    <div className="list-tools"><label><input type="checkbox" checked={filters.watchlist} onChange={event => updateFilters({ watchlist: event.target.checked })} />只看自选</label><span>{data ? `${data.total} 只基金` : '基金目录'}</span><button onClick={() => setRefresh(value => value + 1)} disabled={loading}>刷新数据</button></div>
    {watchError && <p role="alert" className="error">{watchError}</p>}
    {loading ? <section className="market-empty" role="status">正在加载基金…</section> : error ? <section className="market-empty"><p role="alert">{error}</p><button className="secondary" onClick={() => setRefresh(value => value + 1)}>重新加载</button></section> : filters.watchlist && !user ? <section className="market-empty"><h3>登录后，收藏你的关注</h3><p>自选基金会保存在你的独立账户中。</p><a className="secondary" href="#login">登录并查看自选</a></section> : data && <>
      <section className="fund-list" aria-label="基金列表">{data.items.map(fund => <article className="fund-list-row" key={fund.code}>
        <a className="fund-main-link" href={`#fund/${fund.code}?return=${encodeURIComponent(location.hash.slice(1) || 'discover')}`}><div><h3>{fund.name}</h3><p>{fund.category} · {fund.code}</p></div><div className="fund-change"><ChangeValue value={fund.year_change} /><small>近一年净值涨跌</small></div></a>
        <div className="fund-row-meta"><span>净值 {fund.unit_nav ? Number(fund.unit_nav).toFixed(4) : '暂无'} · {fund.nav_date ?? '日期暂无'}</span><button disabled={pending !== null} aria-pressed={fund.is_watched} aria-label={`${fund.is_watched ? '取消自选' : '加入自选'} ${fund.name}`} onClick={() => void toggleWatch(fund.code, !fund.is_watched)}>{pending === fund.code ? '保存中…' : fund.is_watched ? '已自选' : '+ 自选'}</button></div>
        <small className="fund-provenance">{fund.is_sample ? '历史验证样本' : '公开净值 · 本机缓存'} · {formatDate(fund.source_observed_at)} 更新</small>
      </article>)}{data.items.length === 0 && <div className="market-empty"><h3>{filters.watchlist && !filters.q && filters.category === 'all' ? '还没有自选基金' : '没有匹配的基金'}</h3><p>{filters.watchlist ? '试试调整筛选，或浏览全部基金添加自选。' : '试试其他名称、代码或分类。'}</p><button className="secondary" onClick={() => { setInput(''); updateFilters({ q: '', category: 'all', watchlist: false }) }}>查看全部基金</button></div>}</section>
      {hasMore && <div className="fund-load-more" ref={sentinel}>
        {moreError ? <><p role="alert">{moreError}</p><button className="secondary" onClick={() => loadMore.current()}>重试加载</button></> : <button className="secondary" disabled={loadingMore} onClick={() => loadMore.current()}>{loadingMore ? '正在加载…' : '继续下滑，加载更多'}</button>}
      </div>}
      {data.total > 0 && <p className="fund-page-count" role="status">本页已展示 {data.items.length} 只{!hasMore ? batches >= 5 ? ' · 每页最多 50 只' : ' · 已到最后' : ''}</p>}
      {data.total > 0 && <nav className="pagination" aria-label="分页"><button disabled={filters.page <= 1} onClick={() => changePage(filters.page - 1)}>上一页</button><span>第 {filters.page} / {Math.max(1, Math.ceil(data.total / 50))} 页</span><button disabled={hasMore || filters.page * 50 >= data.total} onClick={() => changePage(filters.page + 1)}>下一页</button></nav>}

    </>}
    <p className="data-disclosure">公开基金数据，不代表支付宝在售清单。净值涨跌不含分红再投资；数据不足时显示“—”。</p>
    <aside className="soft-card"><strong>从理解交易规则开始</strong><p>净值、确认时间与费用，都会影响结果。<br />在基金详情中查看来源与费用说明。</p></aside>
    <MarketNavigation active="discover" user={user} />
  </main>
}
