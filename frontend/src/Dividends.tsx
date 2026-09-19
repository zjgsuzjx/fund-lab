import { useEffect, useState } from 'react'
import { api } from './api'
import { formatMoney } from './MarketShared'

type Payments = { policy_note: string; items: { id: string; fund_code: string; record_date: string;
  ex_date: string; pay_date: string; shares: string; cash_per_share: string; amount: string;
  status: string; source_url: string; warning: string }[] }
export default function Dividends({ refresh }: { refresh: number }) {
  const [data, setData] = useState<Payments | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    api<Payments>('/account/dividends', undefined, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value)
    }).catch(reason => { if (!controller.signal.aborted) setError((reason as Error).message) })
    return () => controller.abort()
  }, [refresh, retry])
  return <details className="trade-rules"><summary>现金分红记录</summary>
    {error ? <p role="alert">{error}<button onClick={() => setRetry(v => v + 1)}>重试</button></p> : !data ? <p role="status">正在读取…</p> : <>
      <p>{data.policy_note}</p>
      {!data.items.length && <p>暂无已登记现金分红。</p>}
      {data.items.map(item => <article className="trade-card" key={item.id}>
        <strong>{item.fund_code} · {item.status === 'paid' ? '已到账' : '红利待到账'} · {formatMoney(item.amount)} 元</strong>
        <p>登记日 {item.record_date} · 除息日 {item.ex_date}</p>
        <p>参与份额 {formatMoney(item.shares)} · 每份 {item.cash_per_share} 元</p>
        <p>模拟到账日 {item.pay_date}</p><a href={item.source_url} target="_blank" rel="noreferrer">公告依据 ↗</a>
        {item.warning && <p role="alert">{item.warning}</p>}
      </article>)}
    </>}
  </details>
}
