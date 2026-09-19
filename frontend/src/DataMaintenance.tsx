import { useEffect, useState } from 'react'
import { api, ApiError, type User } from './api'
import { formatDate } from './MarketShared'

type Update = { status: string; message: string; finished_at: string | null }
export default function DataMaintenance({ user, onUpdated }: { user: User | null; onUpdated: () => void }) {
  const [job, setJob] = useState<Update | null>(null)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    async function read() {
      try {
        const next = await api<Update>('/data/update', undefined, controller.signal)
        if (active) { setJob(next); setError('') }
      } catch (reason) { if (active) setError((reason as Error).message) }
      if (active) timer = setTimeout(read, 5000)
    }
    void read()
    return () => { active = false; controller.abort(); clearTimeout(timer) }
  }, [refresh])
  useEffect(() => { if (job?.finished_at) onUpdated() }, [job?.finished_at])
  async function update() {
    setSending(true); setError('')
    try { setJob(await api<Update>('/data/update', {})); setRefresh(v => v + 1) }
    catch (reason) { setError(reason instanceof ApiError && reason.status === 401 ? '请登录后更新基金数据。' : (reason as Error).message) }
    finally { setSending(false) }
  }
  const busy = sending || job?.status === 'queued' || job?.status === 'running'
  return <section aria-label="在线更新基金数据">
    <p>000147 在服务运行时每 6 小时检查更新，失败后自动重试；关机期间暂停，重启后补处理。</p>
    <button className="secondary" disabled={busy || !user} onClick={() => void update()}>{busy ? '更新处理中…' : '更新 000147 数据'}</button>
    {!user && <p><a href="#login">登录后可手动更新</a></p>}
    {job && <p role="status">{job.message}{job.finished_at && <> · {formatDate(job.finished_at)}</>}</p>}
    {error && <p role="alert">{error}<button onClick={() => setRefresh(v => v + 1)}>重试读取</button></p>}
    <p>分红公告补齐除息日并核验后入账；遇到数据修订会保留旧值并暂停相关处理。</p>
  </section>
}
