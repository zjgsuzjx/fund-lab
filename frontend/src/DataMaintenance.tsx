import { useEffect, useRef, useState } from 'react'
import { api, ApiError, type User } from './api'
import { formatDate } from './MarketShared'

type Update = { status: string; message: string; finished_at: string | null }
type Coverage = { fund_count: number; synced_count: number; fresh_count: number; schedule: string; jobs: Record<string, number>; sources: { key: string; status: string; message: string }[] }
export default function DataMaintenance({ user, onUpdated, fundCode }: { user: User | null; onUpdated: () => void; fundCode?: string }) {
  const [job, setJob] = useState<Update | null>(null)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [input, setInput] = useState('')
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const code = fundCode ?? input
  const valid = /^\d{6}$/.test(code)
  const callback = useRef(onUpdated)
  callback.current = onUpdated
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    setJob(null)
    let previousFinished: string | null | undefined
    async function read() {
      try {
        const [summary, next] = await Promise.all([
          api<Coverage>('/data/coverage', undefined, controller.signal),
          valid ? api<Update>(`/data/update?code=${code}`, undefined, controller.signal) : Promise.resolve(null),
        ])
        if (active) {
          setCoverage(summary); setJob(next); setError('')
          if (next?.finished_at && next.finished_at !== previousFinished) callback.current()
          previousFinished = next?.finished_at ?? null
        }
      } catch (reason) { if (active) setError((reason as Error).message) }
      if (active) timer = setTimeout(read, 5000)
    }
    void read()
    return () => { active = false; controller.abort(); clearTimeout(timer) }
  }, [refresh, code, valid])
  async function update() {
    setSending(true); setError('')
    try { setJob(await api<Update>(`/data/update?code=${code}`, {})); setRefresh(v => v + 1) }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 401 ? '请登录后更新基金数据。' : (reason as Error).message) }
    finally { setSending(false) }
  }
  const busy = sending || job?.status === 'queued' || job?.status === 'running'
  return <section aria-label="在线更新基金数据">
    <p>{coverage?.schedule ?? '服务运行时自动同步全市场目录、交易日历与基金净值。'} 关机期间暂停，重启后补处理。</p>
    {coverage && <p>目录 {coverage.fund_count} 只 · 已同步净值 {coverage.synced_count} 只 · 24 小时内更新 {coverage.fresh_count} 只{(coverage.jobs.failed || coverage.jobs.conflict) ? ` · 失败 ${coverage.jobs.failed ?? 0} 只 / 待核验 ${coverage.jobs.conflict ?? 0} 只` : ''}</p>}
    {coverage?.sources.filter(source => source.status !== 'success').map(source => <p key={source.key} role="status">{source.key === 'catalog' ? '基金目录' : '交易日历'}：{source.message}</p>)}
    {!fundCode && <label>更新指定基金 <input aria-label="待更新基金代码" placeholder="输入六位基金代码" value={input} maxLength={6} onChange={event => setInput(event.target.value.replace(/\D/g, ''))} /></label>}
    <button className="secondary" disabled={busy || !user || !valid} onClick={() => void update()}>{busy ? '更新处理中…' : `更新${valid ? ` ${code}` : '基金'}数据`}</button>
    {!user && <p><a href="#login">登录后可手动更新</a></p>}
    {job && <p role="status">{job.message}{job.finished_at && <> · {formatDate(job.finished_at)}</>}</p>}
    {error && <p role="alert">{error}<button onClick={() => setRefresh(v => v + 1)}>重试读取</button></p>}
    <p>分红公告补齐除息日并核验后入账；遇到数据修订会保留旧值并暂停相关处理。</p>
    <p>目录来自公开市场数据，不等同于支付宝当前在售清单。通用模拟费率不代表渠道实际费率。</p>
  </section>
}
