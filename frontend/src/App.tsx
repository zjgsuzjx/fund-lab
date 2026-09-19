import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, type User, type Account, type Ledger } from './api'
import Discover from './Discover'
import FundDetails from './FundDetails'
import './market.css'
import { SellPage, SellOrderPage } from './SellTrading'
import { BuyPage, OrderPage, TradingOverview } from './Trading'

type Page = 'login' | 'register' | 'account' | 'discover' | 'holdings' | 'orders' | `fund/${string}` | `buy/${string}` | `pending/${string}` | `order/${string}` | `sell/${string}` | `sell-order/${string}` | `sell-submitted/${string}`
const route = (): Page => {
  const value = location.hash.slice(1).split('?')[0]
  return ['login', 'register', 'account', 'discover', 'holdings', 'orders'].includes(value) || /^(fund|buy|pending|order|sell|sell-order|sell-submitted)\/[^/]+$/.test(value) ? value as Page : 'discover'
}
const go = (page: Page) => { location.hash = page }
const money = (value: string) => Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function Password({ label, name, autoComplete = 'new-password' }: { label: string; name: string; autoComplete?: string }) {
  const [show, setShow] = useState(false)
  return <label className="field">{label}<span className="password-field"><input name={name} type={show ? 'text' : 'password'} required maxLength={128} autoComplete={autoComplete} placeholder={autoComplete === 'current-password' ? '请输入密码' : '至少 8 位，包含字母和数字'} /><button type="button" onClick={() => setShow(!show)} aria-label={`${show ? '隐藏' : '显示'}${label}`}>{show ? '隐藏' : '显示'}</button></span></label>
}

function Instructions() {
  return <details className="instructions"><summary>使用说明与数据保存说明 · MVP 0.2</summary><p>这是独立模拟产品，与支付宝无关联。所有金额均为虚拟资金，不能充值或提现。账户和练习记录保存在运行服务的本机数据库，不自动同步到其他设备；清理或迁移前请保留数据库备份。用户名不区分大小写，密码区分大小写。</p></details>
}

export default function App() {
  const [page, setPage] = useState<Page>(route)
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)
  const [checkError, setCheckError] = useState('')
  const [notice, setNotice] = useState('')
  const authVersion = useRef(0)
  const check = useCallback(async () => {
    const version = ++authVersion.current
    setCheckError('')
    try {
      const restored = await api<User>('/auth/me')
      if (version === authVersion.current) setUser(restored)
    }
    catch (error) {
      if (version !== authVersion.current) return
      setUser(null)
      if (!(error instanceof ApiError && error.status === 401)) setCheckError((error as Error).message)
    } finally { if (version === authVersion.current) setChecking(false) }
  }, [])
  useEffect(() => {
    const update = () => setPage(route())
    window.addEventListener('hashchange', update)
    void check()
    return () => window.removeEventListener('hashchange', update)
  }, [check])
  useEffect(() => {
    if (checking || checkError) return
    if ((['account', 'holdings', 'orders'].includes(page) || /^(buy|pending|order|sell|sell-order|sell-submitted)\//.test(page)) && !user) { setNotice('请先登录后查看账户。'); go('login') }
    if ((page === 'login' || page === 'register') && user) go('account')
  }, [page, user, checking, checkError])
  // Recheck when returning to a tab, so logout in another tab clears private data.
  useEffect(() => {
    const focus = () => { void check() }
    window.addEventListener('focus', focus)
    return () => window.removeEventListener('focus', focus)
  }, [check])
  function signedOut(message: string) { authVersion.current++; setUser(null); setNotice(message); setPage('login'); go('login') }
  return <>
    {['login', 'register'].includes(page) && <nav className="app-nav" aria-label="主导航"><a href="#discover">基金练习室</a><div><a href="#discover">发现</a><a href={user ? '#account' : '#login'}>{user ? '我的账户' : '登录 / 注册'}</a></div></nav>}
    {checking ? <main className="account-shell"><p role="status">正在恢复登录状态…</p></main> : checkError ? <main className="account-shell"><p className="error" role="alert">{checkError}</p><button className="primary" onClick={() => void check()}>重新连接</button></main> : page === 'discover' ? <Discover key={user?.id ?? 'guest'} user={user} onUnauthorized={signedOut} /> : page.startsWith('fund/') ? <FundDetails key={`${user?.id ?? 'guest'}:${page}`} code={page.slice(5)} user={user} onUnauthorized={signedOut} /> : page.startsWith('sell/') && user ? <SellPage key={`${user.id}:${page}`} code={page.slice(5)} user={user} onUnauthorized={signedOut} /> : /^(sell-order|sell-submitted)\//.test(page) && user ? <SellOrderPage key={`${user.id}:${page}`} id={page.split('/')[1]} submitted={page.startsWith('sell-submitted/')} user={user} onUnauthorized={signedOut} /> : page.startsWith('buy/') && user ? <BuyPage key={`${user.id}:${page}`} code={page.slice(4)} user={user} onUnauthorized={signedOut} /> : /^(pending|order)\//.test(page) && user ? <OrderPage key={`${user.id}:${page}`} id={page.split('/')[1]} pendingPage={page.startsWith('pending/')} user={user} onUnauthorized={signedOut} /> : ['holdings', 'orders'].includes(page) && user ? <TradingOverview key={`${user.id}:${page}`} holdings={page === 'holdings'} user={user} onUnauthorized={signedOut} /> : page === 'account' && user ? <AccountPage user={user} signedOut={signedOut} /> : <AuthForm key={page} register={page === 'register'} notice={notice} onSuccess={value => { authVersion.current++; setUser(value); setNotice(''); setPage('discover'); go('discover') }} />}
  </>
}

function AuthForm({ register, notice, onSuccess }: { register: boolean; notice: string; onSuccess: (user: User) => void }) {
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current) return
    const data = new FormData(event.currentTarget)
    const username = String(data.get('username')).trim()
    const password = String(data.get('password'))
    setError('')
    if (!/^[A-Za-z0-9_]{4,20}$/.test(username)) { setError('用户名须为 4–20 位字母、数字或下划线。'); return }
    if (register && (password.length < 8 || !/[A-Za-z]/.test(password) || !/[0-9]/.test(password))) { setError('密码至少 8 位，且须包含字母和数字。'); return }
    if (register && password !== data.get('confirm')) { setError('两次输入的密码不一致。'); return }
    pending.current = true; setBusy(true)
    try { onSuccess(await api<User>(register ? '/auth/register' : '/auth/login', { username, password, remember: data.get('remember') === 'on' })) }
    catch (reason) { setError((reason as Error).message) }
    finally { pending.current = false; setBusy(false) }
  }
  return <main className="account-shell">
    <h1>{register ? '创建练习账户' : '欢迎回来'}</h1><p className="subtitle">{register ? '从 100,000 元虚拟资金开始' : '登录后，继续你的基金练习'}</p>
    {register ? <aside className="soft-card"><strong>你的第一笔练习本金</strong><b>100,000.00 元 · 无需充值</b></aside> : <aside className="welcome-card"><h2>基金练习室</h2><p>让每一次练习，都有迹可循。</p><small>虚拟资金 / 独立账户 / 本地保存</small></aside>}
    {notice && <p role="status" className="soft-card">{notice}</p>}
    <form onSubmit={submit} className="account-form">
      <fieldset disabled={busy}>
        <label className="field">用户名<input name="username" required minLength={4} maxLength={20} autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder={register ? '例如：fund_learner' : '请输入用户名'} />{register && <small>4–20 位字母、数字或下划线</small>}</label>
        <Password label={register ? '设置密码' : '密码'} name="password" autoComplete={register ? 'new-password' : 'current-password'} />
        {register && <Password label="确认密码" name="confirm" />}
        {register ? <label className="check-field"><input type="checkbox" required />我已阅读使用说明与数据保存说明</label> : <label className="check-field"><input name="remember" type="checkbox" />在这台电脑保持登录（30 天）</label>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit">{busy ? '正在提交…' : register ? '注册并开始练习' : '登录'}</button>
      </fieldset>
    </form>
    <a className="secondary" href={register ? '#login' : '#register'}>{register ? '已有账户？立即登录' : '还没有账户？创建账户'}</a>
    {!register && <details className="instructions"><summary>登录帮助</summary><p>请使用本项目注册的用户名和密码，无需支付宝账号。用户名不区分大小写。忘记密码时请联系本机管理员核验身份；当前版本没有在线找回密码功能。如注册响应中断，可直接尝试登录，已创建账户不会再次发放本金。</p></details>}
    <aside className="soft-card"><strong>{register ? '你将获得' : '账户只用于本地模拟'}</strong><p>{register ? '独立账户、模拟资金流水与已开放基金的买入练习。' : '无需支付宝账号，也无需绑定银行卡。当前版本在这台电脑上保存练习记录。'}</p></aside>
    <Instructions /><footer>这是独立模拟产品，与支付宝无关联</footer>
  </main>
}

function AccountPage({ user, signedOut }: { user: User; signedOut: (message: string) => void }) {
  const [data, setData] = useState<{ account: Account; ledger: Ledger } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [changing, setChanging] = useState(false)
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setData(null)
    Promise.all([api<Account>('/account'), api<Ledger>('/account/ledger')]).then(([account, ledger]) => { if (active) setData({ account, ledger }) }).catch(reason => {
      if (!active) return
      if (reason instanceof ApiError && reason.status === 401) signedOut('登录已过期，请重新登录。')
      else setError((reason as Error).message)
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  // signedOut only updates parent state; reload private data when user or retry changes.
  }, [user.id, refresh])
  async function logout() {
    setBusy(true); setError('')
    try { await api('/auth/logout', {}); signedOut('已安全退出登录。') }
    catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = new FormData(event.currentTarget)
    if (form.get('new_password') !== form.get('confirm')) { setError('两次输入的新密码不一致。'); return }
    setBusy(true); setError('')
    try {
      await api('/account/password', { current_password: form.get('current_password'), new_password: form.get('new_password') })
      signedOut('密码已修改，所有会话已退出，请重新登录。')
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) signedOut('登录已过期，请重新登录。')
      else setError((reason as Error).message)
    } finally { setBusy(false) }
  }
  return <main className="account-shell account-page"><h1>我的账户</h1><p className="subtitle">管理本地账户与练习数据</p>
    <section className="profile-card"><div className="profile"><span className="avatar">{user.username[0].toUpperCase()}</span><div><h2>{user.username}</h2><small>本地账户 · 已登录</small></div></div>
      {data && <><p className="account-row"><span>初始模拟本金</span><strong>{money(data.ledger.items.find(e => e.kind === 'initial_capital')?.amount ?? '0')} 元</strong></p><p className="account-row"><span>可用虚拟资金</span><strong>{money(data.account.available_cash)} 元</strong></p></>}
    </section>
    {loading && <p role="status">正在加载账户…</p>}
    {error && <div className="error" role="alert">{error}<button onClick={() => setRefresh(value => value + 1)} disabled={busy}>重新加载</button></div>}
    <h2 className="account-heading">账户与数据</h2><section className="settings-card"><button onClick={() => setChanging(!changing)} aria-expanded={changing}>修改密码<span>›</span></button><div>导出交易记录<span>暂未开放</span></div><div>备份练习数据<span>暂未开放</span></div><details><summary>数据保存位置<span>本机 ›</span></summary><p>数据保存在运行后端服务的本机 PostgreSQL 数据库中，清理浏览器不会删除账户数据。</p></details></section>
    {changing && <form onSubmit={changePassword} className="account-form"><fieldset disabled={busy}><Password label="当前密码" name="current_password" autoComplete="current-password" /><Password label="新密码" name="new_password" /><Password label="确认新密码" name="confirm" /><button className="primary">{busy ? '正在提交…' : '修改密码并重新登录'}</button></fieldset></form>}
    <h2 className="account-heading">资金流水</h2><section className="profile-card">{data?.ledger.items.map(entry => <div className="ledger-row" key={entry.id}><div><strong>{({ initial_capital: '初始模拟本金', buy_reserved: '买入资金预留', buy_cancelled: '撤单资金退回', buy_confirmed: '买入确认扣除在途', sell_confirmed: '卖出确认转入赎回在途', sell_paid: '赎回资金到账', dividend_paid: '现金分红到账' } as Record<string, string>)[entry.kind] ?? entry.kind}</strong><small>{new Date(entry.created_at).toLocaleString('zh-CN')}</small></div><div><strong>{Number(entry.available_delta) > 0 ? '+' : ''}{money(entry.available_delta)}</strong><small>可用余额 {money(entry.balance_after)}</small><small>买入在途 {Number(entry.reserved_delta) > 0 ? '+' : ''}{money(entry.reserved_delta)}</small><small>赎回在途 {Number(entry.redemption_delta) > 0 ? '+' : ''}{money(entry.redemption_delta)}</small></div></div>)}{data && data.ledger.items.length === 0 && <p>暂无资金流水</p>}</section>
    <aside className="soft-card"><strong>换电脑前，先备份</strong><p>本地账户不自动同步到其他设备。<br />清理数据前请保留一份数据库备份。</p></aside><Instructions />
    <button className="secondary" disabled={busy} onClick={() => void logout()}>{busy ? '正在处理…' : '退出登录'}</button>
    <nav className="bottom-nav" aria-label="账户导航"><a href="#discover">发现</a><a href="#holdings">持仓</a><a href="#orders">交易</a><a href="#account" aria-current="page">我的</a></nav>
  </main>
}
