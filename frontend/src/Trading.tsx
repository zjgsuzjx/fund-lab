import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError, type Account, type BuyQuote, type BuyRequest, type FundDetail, type Order, type Orders, type Portfolio, type SimulationRule, type User } from './api'
import { formatMoney, MarketNavigation } from './MarketShared'
import './trading.css'
import Dividends from './Dividends'

export type Props = { user: User; onUnauthorized: (message: string) => void }
export const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
export const sellStatusName = { pending: '卖出待确认', confirmed: '赎回在途', paid: '资金已到账', cancelled: '卖出已撤销' }
const statusName = { pending: '买入待确认', confirmed: '买入已确认', cancelled: '申请已撤销' }
export const money = (value: string | null) => value === null ? '—' : formatMoney(value)
export function Row({ label, children }: { label: string; children: ReactNode }) { return <div className="trade-row"><span>{label}</span><strong>{children}</strong></div> }
export function Heading({ title, back = 'discover', children }: { title: string; back?: string; children?: ReactNode }) {
  return <><div className="detail-title"><a href={`#${back}`} aria-label="返回">‹</a><h1>{title}</h1></div><p className="trade-subtitle">{children}</p></>
}
export function RuleNote({ rule }: { rule: SimulationRule }) { return <details className="trade-rules"><summary>{rule.name} · 规则与来源</summary><p>{rule.scope}</p>{rule.sources.map(source => <a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.pages ? `招募说明书，第 ${source.pages} 页` : '交易日历来源'} ↗</a>)}</details> }
export function uuid() {
  const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128
  const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
function recover(key: string): BuyRequest | null {
  try { const v = JSON.parse(sessionStorage.getItem(key) ?? 'null'); return v && typeof v.request_key === 'string' && typeof v.amount === 'string' ? v : null } catch { return null }
}

export function BuyPage({ code, user, onUnauthorized }: Props & { code: string }) {
  const storageKey = `fund-lab-buy:${user.id}:${code}`
  const [uncertain, setUncertain] = useState<BuyRequest | null>(() => recover(storageKey))
  const [amount, setAmount] = useState(() => recover(storageKey)?.amount ?? '1000.00')
  const [fund, setFund] = useState<FundDetail | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [quote, setQuote] = useState<BuyQuote | null>(null)
  const [error, setError] = useState('')
  const [quoteError, setQuoteError] = useState('')
  const [loading, setLoading] = useState(true)
  const [quoting, setQuoting] = useState(false)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [retry, setRetry] = useState(0)
  const valid = /^\d+(\.\d{1,2})?$/.test(amount) && Number(amount) >= 1
  function failed(reason: unknown) {
    if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录后查看交易记录。')
    else setError((reason as Error).message)
  }
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    Promise.all([api<FundDetail>(`/funds/${encodeURIComponent(code)}`, undefined, controller.signal), api<Account>('/account', undefined, controller.signal)])
      .then(([f, a]) => { if (!controller.signal.aborted) { setFund(f); setAccount(a) } })
      .catch(reason => { if (!controller.signal.aborted) failed(reason) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [code, user.id, retry])
  useEffect(() => {
    setQuote(null); setQuoteError(''); setQuoting(false)
    if (!valid || !fund?.trade_enabled || uncertain) return
    const controller = new AbortController()
    setQuoting(true)
    const timer = window.setTimeout(() => {
      api<BuyQuote>('/trades/quote', { fund_code: code, amount }, controller.signal)
        .then(value => { if (!controller.signal.aborted) setQuote(value) })
        .catch(reason => { if (!controller.signal.aborted) { if (reason instanceof ApiError && reason.status === 401) failed(reason); else setQuoteError((reason as Error).message) } })
        .finally(() => { if (!controller.signal.aborted) setQuoting(false) })
    }, 300)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [amount, code, fund, retry, uncertain, valid])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending.current || (!uncertain && (!quote || quoting))) return
    const body = uncertain ?? { fund_code: code, amount: quote!.amount, request_key: uuid(), rule_version: quote!.rule_version, trade_date: quote!.trade_date }
    // Persist before sending. A timeout or reload retries this exact intent.
    try { sessionStorage.setItem(storageKey, JSON.stringify(body)) } catch { setError('浏览器无法保存本次请求编号，请允许会话存储后再提交。'); return }
    setUncertain(body); pending.current = true; setBusy(true); setError('')
    try {
      const order = await api<Order>('/orders', body)
      sessionStorage.removeItem(storageKey)
      location.hash = `pending/${order.id}`
    } catch (reason) {
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 401) {
        sessionStorage.removeItem(storageKey); setUncertain(null); setQuote(null); setRetry(v => v + 1)
      }
      failed(reason)
    } finally { pending.current = false; setBusy(false) }
  }
  return <main className="market-shell trade-page"><Heading title="模拟买入" back={`fund/${code}`}>仅使用虚拟余额，不发生真实扣款</Heading>
    {loading ? <p role="status">正在加载买入信息…</p> : fund && account && <form onSubmit={submit}>
      <section className="trade-card buy-amount"><h2>{fund.name}</h2><p className="trade-muted">{fund.code} · {fund.category}</p><label htmlFor="buy-amount">买入金额（元）</label><input id="buy-amount" inputMode="decimal" autoComplete="off" value={amount} maxLength={12} disabled={busy || !!uncertain} onChange={e => { setAmount(e.target.value); setQuote(null); setError('') }} aria-describedby="amount-hint" />
        <p className="trade-muted">可用模拟余额 {money(account.available_cash)} 元</p><div className="quick-amounts">{[100, 1000, 5000].map(value => <button type="button" key={value} disabled={busy || !!uncertain} onClick={() => { setAmount((Number(amount || 0) + value).toFixed(2)); setQuote(null) }}>+{value.toLocaleString()}</button>)}</div>
      </section>
      <section className="trade-card"><h2>这笔买入如何计算</h2><Row label="标准申购费率">{quote?.fee_label ?? '—'}</Row><Row label="预计申购费">{quote ? `${money(quote.fee)} 元` : '—'}</Row><Row label="净申购金额">{quote ? `${money(quote.net_amount)} 元` : '—'}</Row><Row label="确认净值 / 份额"><span className="trade-blue">待公布 / 待确认</span></Row><p className="trade-muted">金额与份额均保留两位小数，四舍五入。</p>{quoting && <p role="status">正在试算费用与交易日期…</p>}</section>
      <aside className="soft-card"><strong>买入不会立即成交</strong><p>{quote ? `计价日 ${quote.trade_date} · 预计 ${quote.confirmation_date} 起确认。` : '交易日 15:00 截止，其后与休市日申请顺延。'}<br />等待对应交易日正式净值，不使用昨日净值或盘中估值。</p>{quote && <p>可撤单至 {time(quote.cancel_until)}（北京时间）。</p>}</aside>
      {fund.simulation_rule && <RuleNote rule={fund.simulation_rule} />}
      <p id="amount-hint" className={!valid ? 'error' : 'trade-muted'}>{!valid ? '请输入不少于 1 元的金额，最多两位小数。' : '1 元起购 · 超出可用余额时无法提交'}</p>
      {!fund.trade_enabled && <p role="alert" className="error">{fund.trade_disabled_reason}</p>}
      {quoteError && <div className="error" role="alert">{quoteError}<button type="button" onClick={() => setRetry(v => v + 1)}>重新试算</button></div>}
      {uncertain && !busy && <p role="status" className="soft-card">上次提交结果尚未确认。重试将查询或完成同一笔申请，不会重复预留资金。也可前往<a href="#orders">交易记录</a>核对。</p>}
      <button className="primary" disabled={busy || (!uncertain && (!quote || quoting || !valid))}>{busy ? '正在提交…' : uncertain ? '重试并确认原申请结果' : `确认模拟买入 · ${valid ? money(amount) : '—'} 元`}</button>
    </form>}
    {error && <div className="error" role="alert">{error}{!fund && <button onClick={() => setRetry(v => v + 1)}>重新加载</button>}</div>}<footer>虚拟资金 · 可查看完整交易记录</footer>
  </main>
}

function Progress({ order }: { order: Order }) {
  return <section className="trade-card"><h2>确认进度</h2><ol className="order-progress"><li><strong>申请已提交</strong><p>{time(order.created_at)} · 虚拟资金已预留</p></li><li><strong>{order.confirmed_nav ? '正式净值已取得' : order.status === 'cancelled' ? '已停止等待净值' : '等待对应正式净值'}</strong><p>计价日 {order.trade_date}{order.confirmed_nav ? ` · 净值 ${Number(order.confirmed_nav).toFixed(4)}` : ' · 不使用盘中估值'}</p></li><li><strong>{order.status === 'confirmed' ? '持仓份额已确认' : order.status === 'cancelled' ? '预留资金已退回' : '确认持仓份额'}</strong><p>{order.completed_at ? time(order.completed_at) : `预计 ${order.confirmation_date} 起，净值缺失则顺延`}</p></li></ol></section>
}
export function CancelDialog({ description, busy, onClose, onConfirm }: { description: string; busy: boolean; onClose: () => void; onConfirm: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close() }, [])
  return <dialog className="cancel-dialog" ref={ref} onCancel={e => { e.preventDefault(); if (!busy) onClose() }} aria-labelledby="cancel-heading"><h2 id="cancel-heading">撤销这笔模拟申请？</h2><p>{description}</p><button autoFocus className="primary" disabled={busy} onClick={onClose}>继续等待确认</button><button className="secondary" disabled={busy} onClick={onConfirm}>{busy ? '正在撤销…' : '确认撤销申请'}</button></dialog>
}
export function OrderPage({ id, pendingPage, user, onUnauthorized }: Props & { id: string; pendingPage: boolean }) {
  const [order, setOrder] = useState<Order | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const generation = useRef(0)
  const [retry, setRetry] = useState(0)
  function failed(reason: unknown) { if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。'); else setError((reason as Error).message) }
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      const version = ++generation.current
      try { const [o, a] = await Promise.all([api<Order>(`/orders/${encodeURIComponent(id)}`, undefined, controller.signal), api<Account>('/account', undefined, controller.signal)]); if (!controller.signal.aborted && version === generation.current) { setOrder(o); setAccount(a) } }
      catch (reason) { if (!controller.signal.aborted) failed(reason) }
      finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    const timer = window.setInterval(() => { if (!pending.current && document.visibilityState === 'visible') void load() }, 15000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [id, user.id, retry])
  async function action(kind: 'cancel' | 'refresh') {
    if (pending.current) return
    generation.current++; pending.current = true; setBusy(true); setError('')
    try { setOrder(await api<Order>(`/orders/${id}/${kind}`, {})); setAccount(await api<Account>('/account')) }
    catch (reason) { failed(reason); setRetry(v => v + 1) }
    finally { pending.current = false; setBusy(false); setCancelOpen(false) }
  }
  return <main className="market-shell trade-page"><Heading title={pendingPage && order ? statusName[order.status] : '交易详情'} back="orders">{pendingPage ? '申请已提交，确认结果会自动更新' : `模拟订单 · ${id}`}</Heading>
    {loading && <p role="status">正在加载订单…</p>}{error && <div className="error" role="alert">{error}<button disabled={busy} onClick={() => setRetry(v => v + 1)}>重新加载</button></div>}
    {order && <><section className="order-summary"><h2>{pendingPage && order.status === 'pending' ? '申请已提交' : statusName[order.status]}</h2><b>¥ {money(order.amount)}</b><p>{order.fund_name} · 模拟申购</p>{pendingPage && <small>{order.status === 'pending' ? '已转入买入在途，暂未计入基金持仓。' : order.status === 'confirmed' ? '已按正式净值确认，可在持仓查看批次。' : '虚拟资金已退回可用余额。'}</small>}</section>
      {!pendingPage && <section className="trade-card"><h2>资金与费用</h2><Row label="支付方式">模拟余额</Row><Row label={order.status === 'pending' ? '预计申购费' : '实际申购费'}>{money(order.status === 'cancelled' ? '0' : order.fee)} 元</Row><Row label={order.status === 'pending' ? '预计净申购金额' : '净申购金额'}>{order.status === 'cancelled' ? '已撤销' : `${money(order.net_amount)} 元`}</Row><Row label="确认净值">{order.confirmed_nav ? Number(order.confirmed_nav).toFixed(4) : '—'}</Row><Row label="确认份额">{order.shares ? `${money(order.shares)} 份` : '—'}</Row></section>}
      <Progress order={order} />
      {pendingPage && account && <section className="trade-card"><Row label="当前可用余额">{money(account.available_cash)} 元</Row><Row label="账户买入在途"><span className="trade-blue">{money(account.reserved_cash)} 元</span></Row></section>}
      {order.status === 'pending' && <><p className="trade-muted">{order.wait_reason}</p><button className="secondary" disabled={busy} onClick={() => void action('refresh')}>{busy ? '正在检查…' : '检查确认结果'}</button></>}
      {pendingPage ? <><a className="primary" href="#holdings">查看我的持仓</a><a className="secondary" href={`#order/${id}`}>查看交易详情 ›</a></> : <><RuleNote rule={order.rule} />{order.can_cancel && <><p className="trade-muted">撤销后，预留的虚拟资金退回可用余额。</p><button className="secondary" disabled={busy} onClick={() => setCancelOpen(true)}>撤销模拟申请</button></>}<p className="trade-muted">{order.can_cancel ? '可撤单' : '撤单已关闭'} · 截止 {time(order.cancel_until)}（北京时间）</p><a className="secondary" href="#holdings">查看我的持仓</a></>}
      {cancelOpen && <CancelDialog description={`撤销后，${money(order.amount)} 元预留资金将退回可用余额，不收取申购费。`} busy={busy} onClose={() => setCancelOpen(false)} onConfirm={() => void action('cancel')} />}
    </>}
  </main>
}

export function TradingOverview({ holdings, user, onUnauthorized }: Props & { holdings: boolean }) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [orders, setOrders] = useState<Orders | null>(null)
  const [status, setStatus] = useState('all')
  const [kind, setKind] = useState('all')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    const request = holdings ? api<Portfolio>('/holdings', undefined, controller.signal).then(v => { if (!controller.signal.aborted) setPortfolio(v) }) : api<Orders>(`/orders?status=${status}&kind=${kind}&page=${page}`, undefined, controller.signal).then(v => { if (!controller.signal.aborted) setOrders(v) })
    request.catch(reason => { if (controller.signal.aborted) return; if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。'); else setError((reason as Error).message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [holdings, user.id, status, kind, page, retry])
  return <main className="market-shell trade-page"><Heading title={holdings ? '我的持仓' : '交易记录'}>{holdings ? '看清现金、在途与已确认份额' : '每一次模拟操作，都有迹可循'}</Heading>
    {!holdings && <div className="category-tabs" aria-label="订单状态">{[['all', '全部'], ['pending', '待确认'], ['confirmed', '已确认'], ['paid', '已到账'], ['cancelled', '已撤销']].map(([v, text]) => <button key={v} aria-pressed={status === v} onClick={() => { setStatus(v); setPage(1) }}>{text}</button>)}</div>}
    {!holdings && <label className="trade-filter">交易类型 <select value={kind} onChange={e => { setKind(e.target.value); setPage(1) }}><option value="all">全部</option><option value="buy">买入</option><option value="sell">卖出</option></select></label>}
    {loading ? <p role="status">正在加载…</p> : error ? <div className="error" role="alert">{error}<button onClick={() => setRetry(v => v + 1)}>重新加载</button></div> : holdings && portfolio ? <><section className="order-summary"><p>模拟总资产（元）</p><b>{money(portfolio.total_assets)}</b><Row label="可用余额">{money(portfolio.available_cash)}</Row><Row label="买入在途">{money(portfolio.reserved_cash)}</Row><Row label="赎回在途">{money(portfolio.redemption_cash)}</Row><Row label="红利待到账">{money(portfolio.dividend_cash)}</Row><Row label="持仓市值">{money(portfolio.market_value)}</Row><Row label="累计收益（含费用和现金分红）">{money(portfolio.total_profit)}</Row><Row label="已实现收益（含现金分红）">{money(portfolio.realized_profit)}</Row></section><p className="trade-muted">{portfolio.valuation_note}</p>
      {(Number(portfolio.reserved_cash) > 0 || Number(portfolio.redemption_cash) > 0) && <a className="secondary" href="#orders">查看待处理申请 ›</a>}
      {portfolio.items.length === 0 ? <section className="market-empty"><h2>暂无已确认持仓</h2><p>买入在途尚未计入持仓，确认后显示实际份额。</p><a href="#discover">去发现基金 ›</a></section> : portfolio.items.map(item => <section className="trade-card" key={item.fund_code}><a href={`#fund/${item.fund_code}`}><h2>{item.fund_name} ›</h2></a><p className="trade-muted">{item.fund_code} · 净值日期 {item.nav_date}</p><Row label="持仓市值">{money(item.market_value)} 元</Row><Row label="持仓份额">{money(item.shares)} 份</Row><Row label="冻结份额">{money(item.frozen_shares)} 份</Row><Row label="本次计价日可赎回">{money(item.available_shares)} 份</Row><Row label="剩余成本（含申购费）">{money(item.cost)} 元</Row><Row label="持仓净值收益">{money(item.holding_profit)} 元</Row><div className="position-actions"><a href={`#buy/${item.fund_code}`}>追加买入</a><a href={`#sell/${item.fund_code}`}>卖出份额</a></div>{item.sell_disabled_reason && <p className="trade-muted">{item.sell_disabled_reason}</p>}<details className="trade-rules"><summary>查看确认批次</summary>{item.lots.map(lot => <a key={lot.order_id} href={`#order/${lot.order_id}`}>{lot.confirmation_date} · {money(lot.shares)} 份 ›</a>)}</details></section>)}<Dividends refresh={retry} /><button className="secondary" onClick={() => setRetry(v => v + 1)}>刷新持仓</button></> : orders && <><div className="order-list">{orders.items.length ? orders.items.map(order => <a className="trade-card order-link" key={order.id} href={`#${order.kind === 'sell' ? 'sell-order' : 'order'}/${order.id}`}><span className="trade-blue">{order.kind === 'sell' ? sellStatusName[order.status] : statusName[order.status]}</span><h2>{order.fund_name}</h2><Row label={time(order.created_at)}>{order.kind === 'sell' ? `${money(order.shares)} 份` : `${money(order.amount)} 元`} ›</Row></a>) : <section className="market-empty"><h2>暂无相关交易</h2><p>模拟买入后，在这里查看进度与记录。</p><a href="#discover">去发现基金 ›</a></section>}</div><div className="pagination"><button disabled={page <= 1} onClick={() => setPage(v => v - 1)}>上一页</button><span>第 {page} 页 · 共 {orders.total} 笔</span><button disabled={page * 20 >= orders.total} onClick={() => setPage(v => v + 1)}>下一页</button></div></>}
    <MarketNavigation active={holdings ? 'holdings' : 'orders'} user={user} />
  </main>
}
