import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import './password-dialog.css'
import './reset-dialog.css'

export default function ResetDataDialog({ userId, onClose, signedOut }: { userId: string; onClose: () => void; signedOut: (message: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const element = dialog.current!
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    return () => { element.close(); document.body.style.overflow = overflow }
  }, [])
  function close() { if (!pending.current) onClose() }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current) return
    const form = new FormData(event.currentTarget)
    pending.current = true; setBusy(true); setError('')
    try {
      await api('/account/reset', { current_password: form.get('current_password') })
      try {
        Object.keys(sessionStorage).filter(key => key.startsWith(`fund-lab-buy:${userId}:`) || key.startsWith(`fund-lab-sell:${userId}:`)).forEach(key => sessionStorage.removeItem(key))
      } catch { /* Storage may be unavailable; server reset has already succeeded. */ }
      signedOut('个人数据已重置，模拟本金已恢复为 100,000 元，请重新登录。')
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) signedOut('会话已失效，请重新登录查看账户状态。')
      else setError(reason instanceof ApiError ? reason.message : '请求结果暂未确认，请重新登录查看账户状态，避免重复操作。')
    } finally { pending.current = false; setBusy(false) }
  }
  return <dialog className="password-dialog reset-dialog" ref={dialog} aria-labelledby="reset-title" aria-describedby="reset-description" onCancel={event => { event.preventDefault(); close() }}>
    <header className="password-dialog-header"><div><h2 id="reset-title">重置个人数据</h2><p>重新开始一段模拟投资</p></div><button type="button" autoFocus disabled={busy} onClick={close}>取消</button></header>
    <div className="reset-warning" id="reset-description"><strong>此操作不可恢复</strong><p>将清空你的持仓、买卖订单、收益与分红记录、资金流水及自选基金，包括尚未完成的交易。</p><p>账号与密码保留，模拟本金恢复为 <b>100,000 元</b>。公共基金数据及其他用户不受影响。</p></div>
    <form onSubmit={submit} aria-busy={busy}><fieldset disabled={busy}>
      <label className="field">当前登录密码<input type="password" name="current_password" autoComplete="current-password" placeholder="输入密码以确认重置" required maxLength={128} /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <p className="password-session-note">重置成功后，所有已登录会话将退出，需要重新登录。</p>
      <button className="primary reset-confirm" type="submit">{busy ? '正在重置，请稍候…' : '确认重置个人数据'}</button>
    </fieldset></form>
  </dialog>
}
