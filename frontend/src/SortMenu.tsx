import { useEffect, useRef, useState } from 'react'
import './sort-menu.css'

const options = [
  ['code', '基金代码', '按基金代码'],
  ['name', '基金名称', '按名称排序'],
  ['change_desc', '近一年净值涨幅', '从高到低 · 默认'],
  ['change_asc', '近一年净值涨幅', '从低到高'],
  ['nav_desc', '单位净值', '从高到低'],
] as const

export default function SortMenu({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const current = options.find(option => option[0] === value) ?? options[2]
  useEffect(() => {
    if (!open) return
    root.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus({ preventScroll: true })
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); event.preventDefault() }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [open])
  return <div className="fund-sort" ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}>
    <button className="fund-sort-trigger" ref={trigger} type="button" aria-label={`基金排序：${current[1]}，${current[2]}`} aria-expanded={open} aria-controls="fund-sort-options" onClick={() => setOpen(!open)}>
      <span>{current[1]}{value.endsWith('desc') ? ' ↓' : value.endsWith('asc') ? ' ↑' : ''}</span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
    </button>
    {open && <div id="fund-sort-options" className="fund-sort-options" role="group" aria-label="基金排序方式">
      <p>排序方式</p>
      {options.map(([key, label, description]) => <button type="button" key={key} aria-pressed={value === key} onClick={() => { onChange(key); setOpen(false); trigger.current?.focus() }}>
        <span><strong>{label}</strong><small>{description}</small></span>
        {value === key && <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>}
      </button>)}
    </div>}
  </div>
}
