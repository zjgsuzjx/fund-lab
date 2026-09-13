import type { User } from './api'
export const formatMoney = (value: string) => Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '暂无'
export function ChangeValue({ value }: { value: string | null }) {
  return <strong className={value === null ? 'change-missing' : Number(value) > 0 ? 'change-up' : Number(value) < 0 ? 'change-down' : 'change-flat'}>{value === null ? '—' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}%`}</strong>
}
export function MarketNavigation({ active, user }: { active: 'discover' | 'account'; user: User | null }) {
  return <nav className="market-nav" aria-label="主导航"><a href="#discover" aria-current={active === 'discover' ? 'page' : undefined}>发现</a><span title="持仓功能将在模拟交易阶段开放">持仓<small>待开放</small></span><span title="交易功能将在下一阶段开放">交易<small>待开放</small></span><a href={user ? '#account' : '#login'} aria-current={active === 'account' ? 'page' : undefined}>我的</a></nav>
}
