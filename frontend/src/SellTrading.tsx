import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type SellContext, type SellOrder, type SellQuote, type SellRequest } from './api'
import { CancelDialog, Heading, Row, RuleNote, money, sellStatusName, time, uuid, type Props } from './Trading'

function recover(key: string): SellRequest | null {
  try { const value = JSON.parse(sessionStorage.getItem(key) ?? 'null'); return value && typeof value.shares === 'string' && typeof value.request_key === 'string' && typeof value.quote_token === 'string' ? value : null } catch { return null }
}

export function SellPage({ code, user, onUnauthorized }: Props & { code: string }) {
  const key = `fund-lab-sell:${user.id}:${code}`
  const [uncertain, setUncertain] = useState<SellRequest | null>(() => recover(key))
  const [shares, setShares] = useState(() => recover(key)?.shares ?? '')
  const [context, setContext] = useState<SellContext | null>(null)
  const [quote, setQuote] = useState<SellQuote | null>(null)
  const [error, setError] = useState('')
  const [quoteError, setQuoteError] = useState('')
  const [loading, setLoading] = useState(true)
  const [quoting, setQuoting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  const pending = useRef(false)
  const valid = /^\d+(\.\d{1,2})?$/.test(shares) && Number(shares) >= 0.01
  function failed(reason: unknown) {
    if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录后核对交易记录。')
    else setError((reason as Error).message)
  }
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    api<SellContext>(`/redemptions/context/${encodeURIComponent(code)}`, undefined, controller.signal)
      .then(value => { if (!controller.signal.aborted) setContext(value) })
      .catch(reason => { if (!controller.signal.aborted) failed(reason) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [code, user.id, retry])
  useEffect(() => {
    setQuote(null); setQuoteError(''); setQuoting(false)
    if (!valid || !context || context.disabled_reason || uncertain) return
    const controller = new AbortController()
    setQuoting(true)
    const timer = window.setTimeout(() => {
      api<SellQuote>('/redemptions/quote', { fund_code: code, shares }, controller.signal)
        .then(value => { if (!controller.signal.aborted) setQuote(value) })
        .catch(reason => { if (!controller.signal.aborted) { if (reason instanceof ApiError && reason.status === 401) failed(reason); else setQuoteError((reason as Error).message) } })
        .finally(() => { if (!controller.signal.aborted) setQuoting(false) })
    }, 300)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [shares, context, retry, uncertain, valid, code])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending.current || (!uncertain && (!quote || quoting))) return
    const body = uncertain ?? { fund_code: code, shares: quote!.shares, request_key: uuid(), quote_token: quote!.quote_token }
    try { sessionStorage.setItem(key, JSON.stringify(body)) } catch { setError('浏览器无法保存本次请求编号，请允许会话存储后再提交。'); return }
    pending.current = true; setBusy(true); setUncertain(body); setError('')
    try {
      const order = await api<SellOrder>('/redemptions', body)
      sessionStorage.removeItem(key)
      location.hash = `sell-submitted/${order.id}`
    } catch (reason) {
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 401) {
        sessionStorage.removeItem(key); setUncertain(null); setQuote(null); setRetry(v => v + 1)
      }
      failed(reason)
    } finally { pending.current = false; setBusy(false) }
  }
  function fraction(divisor: number) {
    if (!context) return
    // Share quantities are integer hundredths; floor partial shortcuts, preserve exact full balance.
    const cents = Math.round(Number(context.available_shares) * 100)
    setShares((Math.floor(cents / divisor) / 100).toFixed(2)); setQuote(null); setError('')
  }
  return <main className="market-shell trade-page"><Heading title="模拟卖出" back="holdings">赎回份额，金额以确认净值为准</Heading>
    {loading ? <p role="status">正在加载可赎回份额…</p> : context && <form onSubmit={submit}>
      <section className="trade-card buy-amount"><h2>{context.fund_name}</h2><label htmlFor="sell-shares">卖出份额（份）</label><input id="sell-shares" inputMode="decimal" autoComplete="off" placeholder="0.00" value={shares} maxLength={12} disabled={busy || !!uncertain} onChange={e => { setShares(e.target.value); setQuote(null); setError('') }} aria-describedby="shares-hint" /><p className="trade-muted">本次计价日可赎回 {money(context.available_shares)} 份 · 已冻结 {money(context.frozen_shares)} 份</p><div className="quick-amounts">{[[4, '1/4'], [2, '1/2'], [1, '全部']].map(([divisor, label]) => <button type="button" key={divisor} disabled={busy || !!uncertain} onClick={() => fraction(Number(divisor))}>{label}</button>)}</div></section>
      <section className="trade-card"><h2>预计到账试算</h2><Row label={`参考净值（${quote?.reference_date ?? context.reference_date ?? '暂无'}）`}>{context.reference_nav ? Number(quote?.reference_nav ?? context.reference_nav).toFixed(4) : '—'}</Row><Row label="预计赎回金额">{quote ? `${money(quote.gross_amount)} 元` : '—'}</Row><Row label="赎回费率">按各批持有期分别计算</Row><Row label="预计赎回费">{quote ? `${money(quote.fee)} 元` : '—'}</Row><div className="sell-net"><Row label="预计净到账">{quote ? `${money(quote.net_amount)} 元` : '—'}</Row></div>{quoting && <p role="status">正在试算批次费用…</p>}
        {quote && <details className="trade-rules"><summary>查看 {quote.allocations.length} 笔批次费用</summary>{quote.allocations.map(a => <div className="sell-lot" key={a.lot_id}><p>{a.confirmation_date} 买入确认 · {money(a.shares)} 份</p><p>至预计赎回确认日持有 {a.holding_days} 天 · 费率 {(Number(a.fee_rate) * 100).toFixed(2)}% · 预计费用 {money(a.fee)} 元</p></div>)}</details>}
      </section>
      <aside className="soft-card"><strong>确认后仍需等待到账</strong><p>参考净值仅用于试算，不锁定成交价。<br />提交 → 净值确认 → 赎回在途 → 到账</p><p>计价日 {quote?.trade_date ?? context.trade_date ?? '待核验'}<br />预计 {quote?.confirmation_date ?? context.confirmation_date ?? '待核验'} 起确认，{quote?.arrival_date ?? context.arrival_date ?? '待核验'} 到账。</p><p>T+7 到账为本模拟方案约定；净值缺失或异常则继续等待。所有日期按北京时间。</p></aside>
      <RuleNote rule={context.rule} />
      <p id="shares-hint" className="trade-muted">0.01 份起赎，最多两位小数。买入待确认、未到可赎回日或已冻结的份额不能卖出。</p>
      {shares && !valid && <p className="error" role="alert">请输入不少于 0.01 份的数量，最多两位小数。</p>}
      {context.disabled_reason && <p className="error" role="alert">{context.disabled_reason}</p>}
      {!context.disabled_reason && Number(context.available_shares) === 0 && <p className="soft-card">暂无可赎回份额，可返回持仓查看确认与冻结状态。</p>}
      {quoteError && <div className="error" role="alert">{quoteError}<button type="button" onClick={() => setRetry(v => v + 1)}>重新试算</button></div>}
      {uncertain && !busy && <p className="soft-card" role="status">上次申请结果尚未确认。重试将使用原请求编号，不会重复冻结份额。也可先查看<a href="#orders">交易记录</a>。</p>}
      <button className="primary" disabled={busy || (!uncertain && (!quote || quoting || !valid))}>{busy ? '正在提交…' : uncertain ? '重试并确认原卖出结果' : `确认模拟卖出 · ${valid ? money(shares) : '—'} 份`}</button>
    </form>}
    {error && <div className="error" role="alert">{error}{!context && <button onClick={() => setRetry(v => v + 1)}>重新加载</button>}</div>}
    <footer>虚拟份额 · 费用与到账金额以确认结果为准</footer>
  </main>
}

export function SellOrderPage({ id, submitted, user, onUnauthorized }: Props & { id: string; submitted: boolean }) {
  const [order, setOrder] = useState<SellOrder | null>(null)
  const [context, setContext] = useState<SellContext | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [retry, setRetry] = useState(0)
  const pending = useRef(false)
  const generation = useRef(0)
  function failed(reason: unknown) { if (reason instanceof ApiError && reason.status === 401) onUnauthorized('登录已过期，请重新登录。'); else setError((reason as Error).message) }
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      const version = ++generation.current
      try {
        const o = await api<SellOrder>(`/redemptions/${encodeURIComponent(id)}`, undefined, controller.signal)
        const c = await api<SellContext>(`/redemptions/context/${o.fund_code}`, undefined, controller.signal)
        if (!controller.signal.aborted && version === generation.current) { setOrder(o); setContext(c) }
      } catch (reason) { if (!controller.signal.aborted && version === generation.current) failed(reason) }
      finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    const timer = window.setInterval(() => { if (!pending.current && document.visibilityState === 'visible') void load() }, 15000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [id, user.id, retry])
  async function action(kind: 'cancel' | 'refresh') {
    if (pending.current) return
    generation.current++; pending.current = true; setBusy(true); setError('')
    try { const o = await api<SellOrder>(`/redemptions/${id}/${kind}`, {}); setOrder(o); setContext(await api<SellContext>(`/redemptions/context/${o.fund_code}`)) }
    catch (reason) { failed(reason) }
    finally { pending.current = false; setBusy(false); setCancelOpen(false) }
  }
  const actual = order?.status === 'confirmed' || order?.status === 'paid'
  return <main className="market-shell trade-page"><Heading title={submitted && order?.status === 'pending' ? '卖出申请已提交' : '卖出交易详情'} back="orders">{submitted ? '确认后转为赎回在途，到账后转为可用余额' : `模拟订单 · ${id}`}</Heading>
    {loading && <p role="status">正在加载订单…</p>}{error && <div className="error" role="alert">{error}<button disabled={busy} onClick={() => { setError(''); setRetry(v => v + 1) }}>重新加载</button></div>}
    {order && <><section className="order-summary"><h2>{sellStatusName[order.status]}</h2><b>{money(order.shares)} 份</b><p>{order.fund_name} · {order.fund_code}</p><small>{order.status === 'cancelled' ? '已释放冻结份额，不收取赎回费。' : actual ? `确认净到账 ${money(order.net_amount)} 元${order.status === 'confirmed' ? ' · 尚不可用' : ' · 已转入可用余额'}` : `预计净到账 ${money(order.quote.net_amount)} 元 · 非最终金额`}</small></section>
      <section className="trade-card"><h2>这笔卖出接下来会发生什么</h2><ol className="order-progress"><li><strong>申请已提交</strong><p>{time(order.created_at)} · 冻结 {money(order.shares)} 份</p></li><li><strong>{actual ? '赎回金额已确认' : order.status === 'cancelled' ? '已撤销，停止确认' : '等待净值确认'}</strong><p>计价日 {order.trade_date} · {order.confirmed_at ? time(order.confirmed_at) : `预计 ${order.confirmation_date} 起确认`}</p></li><li><strong>{order.status === 'paid' ? '资金已到账' : order.status === 'cancelled' ? '冻结份额已释放' : '等待资金到账'}</strong><p>{order.paid_at ? time(order.paid_at) : order.status === 'cancelled' && order.completed_at ? time(order.completed_at) : `模拟约定 ${order.arrival_date} 到账（T+7）`}</p></li></ol></section>
      <section className="trade-card"><h2>{actual ? '确认金额与费用' : '提交时费用试算'}</h2><Row label={actual ? '确认净值' : `参考净值（${order.quote.reference_date}）`}>{Number(actual ? order.confirmed_nav : order.quote.reference_nav).toFixed(4)}</Row><Row label={actual ? '赎回金额' : '预计赎回金额'}>{money(actual ? order.gross_amount : order.quote.gross_amount)} 元</Row><Row label={actual ? '实际赎回费' : '预计赎回费'}>{money(order.status === 'cancelled' ? '0' : actual ? order.fee : order.quote.fee)} 元</Row><Row label={actual ? '确认净到账' : '预计净到账'}>{order.status === 'cancelled' ? '已撤销' : `${money(actual ? order.net_amount : order.quote.net_amount)} 元`}</Row>
        <details className="trade-rules"><summary>查看批次与费用</summary>{order.allocations.map(a => <div className="sell-lot" key={a.lot_id}><p>{money(a.shares)} 份 · 持有 {a.holding_days} 天 · {(Number(a.fee_rate) * 100).toFixed(2)}%</p>{actual && <p>赎回费 {money(a.fee)} 元 · 结转成本 {money(a.cost)} 元</p>}</div>)}</details>
      </section>
      {submitted && context && <section className="trade-card"><Row label="当前可赎回份额">{money(context.available_shares)} 份</Row><Row label="本次仍冻结份额">{order.status === 'pending' ? money(order.shares) : '0.00'} 份</Row></section>}
      {order.wait_reason && <p className="trade-muted">{order.wait_reason}</p>}
      {['pending', 'confirmed'].includes(order.status) && <button className="secondary" disabled={busy} onClick={() => void action('refresh')}>{busy ? '正在检查…' : '检查确认与到账结果'}</button>}
      <RuleNote rule={order.rule} />
      {order.can_cancel && <button className="secondary" disabled={busy} onClick={() => setCancelOpen(true)}>撤销模拟卖出</button>}
      <p className="trade-muted">{order.can_cancel ? '可撤单' : '撤单已关闭'} · 截止 {time(order.cancel_until)}（北京时间）</p>
      <a className="primary" href="#orders">查看交易记录</a><a className="secondary" href="#holdings">返回我的持仓</a>
      {cancelOpen && <CancelDialog description={`撤销后将释放 ${money(order.shares)} 份冻结份额，不收取赎回费。`} busy={busy} onClose={() => setCancelOpen(false)} onConfirm={() => void action('cancel')} />}
    </>}
  </main>
}
