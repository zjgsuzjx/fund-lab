import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from './api'
import './password-dialog.css'

export default function PasswordDialog({ onClose, signedOut }: { onClose: () => void; signedOut: (message: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const pending = useRef(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [visible, setVisible] = useState<Record<string, boolean>>({})
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
    const password = String(form.get('new_password') ?? '')
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) { setError('新密码至少 8 位，且须包含字母和数字。'); return }
    if (password !== form.get('confirm')) { setError('两次输入的新密码不一致，请重新确认。'); return }
    pending.current = true; setBusy(true); setError('')
    try {
      await api('/account/password', { current_password: form.get('current_password'), new_password: password })
      signedOut('密码已修改，所有会话已退出，请使用新密码登录。')
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) signedOut('登录已过期，请重新登录。')
      else setError((reason as Error).message)
    } finally { pending.current = false; setBusy(false) }
  }
  return <dialog className="password-dialog" ref={dialog} aria-labelledby="password-dialog-title" aria-describedby="password-dialog-description" onCancel={event => { event.preventDefault(); close() }}>
    <header className="password-dialog-header"><div><h2 id="password-dialog-title">修改密码</h2><p id="password-dialog-description">验证当前密码，为账户设置新密码</p></div><button type="button" disabled={busy} onClick={close} aria-label="关闭修改密码">取消</button></header>
    <form onSubmit={submit} aria-busy={busy}>
      <fieldset disabled={busy}>
        {([['current_password', '当前密码', '输入当前登录密码'], ['new_password', '新密码', '至少 8 位，包含字母和数字'], ['confirm', '确认新密码', '再次输入新密码']] as const).map(([name, label, placeholder]) => <label className="field" key={name}>{label}<span className="password-field"><input name={name} type={visible[name] ? 'text' : 'password'} autoFocus={name === 'current_password'} autoComplete={name === 'current_password' ? 'current-password' : 'new-password'} required maxLength={128} placeholder={placeholder} aria-describedby={name === 'new_password' ? 'password-requirements' : undefined} /><button type="button" aria-label={`${visible[name] ? '隐藏' : '显示'}${label}`} aria-pressed={!!visible[name]} onClick={() => setVisible(value => ({ ...value, [name]: !value[name] }))}>{visible[name] ? '隐藏' : '显示'}</button></span></label>)}
        <p className="password-requirements" id="password-requirements">8–128 位，包含字母和数字，区分大小写。</p>
        {error && <p className="error" role="alert">{error}</p>}
        <p className="password-session-note">修改成功后，所有已登录会话将退出，需要使用新密码重新登录。</p>
        <button className="primary" type="submit">{busy ? '正在修改…' : '确认修改密码'}</button>
      </fieldset>
    </form>
  </dialog>
}
