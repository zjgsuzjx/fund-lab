import type { User } from './api'
export const formatMoney = (value: string) => Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '暂无'
export function ChangeValue({ value }: { value: string | null }) {
  return <strong className={value === null ? 'change-missing' : Number(value) > 0 ? 'change-up' : Number(value) < 0 ? 'change-down' : 'change-flat'}>{value === null ? '—' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}%`}</strong>
}
export function MarketNavigation({ active, user }: { active: 'discover' | 'account' | 'holdings' | 'orders'; user: User | null }) {
  return <nav className="market-nav" aria-label="主导航">{([
    ['discover', '发现', 'compass'], ['holdings', '持有', 'briefcase-business'],
    ['orders', '交易', 'chart-no-axes-column'], ['account', '我的', 'user-round'],
  ] as const).map(([page, label, icon]) => <a key={page} href={page === 'discover' || user ? `#${page}` : '#login'} aria-current={active === page ? 'page' : undefined}><img src={`/assets/${icon}.svg`} width="23" height="23" alt="" />{label}</a>)}</nav>
}
