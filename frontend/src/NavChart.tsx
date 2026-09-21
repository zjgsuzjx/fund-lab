import { useEffect, useRef, useState } from 'react'
import type { NavHistory } from './api'
import './nav-chart.css'

const percent = (value: number) => `${Math.abs(value) < .005 ? '' : value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(2)}%`

export default function NavChart({ data }: { data: NavHistory }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [mode, setMode] = useState<'percent' | 'nav'>('percent')
  const points = data.items
  const base = points.length ? Number(points[0].unit_nav) : 1
  const values = points.map(p => mode === 'percent' ? (Number(p.unit_nav) / base - 1) * 100 : Number(p.unit_nav))
  const format = (value: number) => mode === 'percent' ? percent(value) : value.toFixed(4)
  useEffect(() => { setSelected(null) }, [data])
  useEffect(() => {
    const element = canvas.current
    if (!element || !points.length) return
    const draw = () => {
      const width = element.clientWidth, height = element.clientHeight, ratio = window.devicePixelRatio || 1
      if (!width || !height) return
      element.width = width * ratio; element.height = height * ratio
      const ctx = element.getContext('2d')!
      ctx.scale(ratio, ratio)
      const low = Math.min(...values), high = Math.max(...values)
      const pad = Math.max((high - low) * .15, mode === 'percent' ? .01 : Math.abs(low) * .0001), min = low - pad, max = high + pad
      ctx.font = '10px "Microsoft YaHei",sans-serif'
      const left = Math.max(54, ...[min, max].map(v => ctx.measureText(format(v)).width + 10)), right = width - 8, top = 14, bottom = height - 30
      const dates = points.map(p => Date.parse(p.date)), start = dates[0], end = dates[dates.length - 1]
      const x = (i: number) => end === start ? (left + right) / 2 : left + (dates[i] - start) / (end - start) * (right - left)
      const y = (v: number) => bottom - (v - min) / (max - min) * (bottom - top)
      ctx.font = '10px "Microsoft YaHei",sans-serif'; ctx.fillStyle = '#64748b'; ctx.strokeStyle = '#e4eaf3'; ctx.lineWidth = 1
      element.dataset.plotLeft = String(left)
      ctx.setLineDash([3, 4])
      for (let i = 0; i < 5; i++) { const value = min + (max - min) * i / 4; const yy = y(value); ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(right, yy); ctx.stroke(); ctx.fillText(format(value), 0, yy + 3) }
      if (mode === 'percent') { ctx.beginPath(); ctx.moveTo(left, y(0)); ctx.lineTo(right, y(0)); ctx.strokeStyle = '#a5b5ca'; ctx.stroke() }
      ctx.setLineDash([])
      ctx.beginPath(); values.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)))
      ctx.lineTo(x(points.length - 1), bottom); ctx.lineTo(x(0), bottom); ctx.closePath()
      const fill = ctx.createLinearGradient(0, top, 0, bottom); fill.addColorStop(0, '#1677ff30'); fill.addColorStop(1, '#1677ff00'); ctx.fillStyle = fill; ctx.fill()
      ctx.beginPath(); values.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)))
      ctx.strokeStyle = '#1768e8'; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke()
      const index = Math.min(selected ?? points.length - 1, points.length - 1)
      if (index !== null && points[index]) {
        ctx.beginPath(); ctx.arc(x(index), y(values[index]), 3.5, 0, Math.PI * 2); ctx.fillStyle = '#1768e8'; ctx.fill()
        ctx.beginPath(); ctx.moveTo(x(index), top); ctx.lineTo(x(index), bottom); ctx.strokeStyle = '#9bbef5'; ctx.lineWidth = 1; ctx.stroke()
      }
      ctx.fillStyle = '#64748b'; ctx.fillText(points[0].date, left, height - 7); ctx.textAlign = 'right'; if (points.length > 1) ctx.fillText(points[points.length - 1].date, right, height - 7)
    }
    const observer = new ResizeObserver(draw); observer.observe(element); draw()
    return () => observer.disconnect()
  }, [points, selected, mode])
  if (!points.length) return <div className="chart-empty">暂无可显示的净值数据</div>
  const index = Math.min(selected ?? points.length - 1, points.length - 1)
  return <><div className="nav-chart-toolbar"><div className="nav-chart-modes" role="group" aria-label="走势图显示方式">{([['percent', '涨跌幅'], ['nav', '单位净值']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)}>{label}</button>)}</div><span>滑动查看</span></div>
  <div className="nav-chart-value" aria-live="polite"><div><span>{mode === 'percent' ? '相对起点涨跌' : '单位净值'}</span><strong className={mode === 'percent' ? values[index] > 0 ? 'is-up' : values[index] < 0 ? 'is-down' : '' : ''}>{format(values[index])}</strong></div><time>{points[index].date}</time></div>
  <canvas ref={canvas} className="nav-canvas" role="img" aria-label={`${mode === 'percent' ? '单位净值涨跌幅' : '单位净值'}走势，从 ${points[0].date} 至 ${points[points.length - 1].date}，共 ${points.length} 个数据点。可使用下方滑块查看具体日期。`} onPointerMove={event => {
    const rect = event.currentTarget.getBoundingClientRect()
    const left = Number(event.currentTarget.dataset.plotLeft || 54)
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - left) / Math.max(1, rect.width - left - 8)))
    const target = Date.parse(points[0].date) + ratio * (Date.parse(points[points.length - 1].date) - Date.parse(points[0].date))
    let nearest = 0
    points.forEach((point, index) => { if (Math.abs(Date.parse(point.date) - target) < Math.abs(Date.parse(points[nearest].date) - target)) nearest = index })
    setSelected(nearest)
  }} /><label className="chart-slider"><span className="sr-only">选择净值日期</span><input aria-label="选择净值日期" aria-valuetext={`${points[index].date}，${format(values[index])}`} type="range" min="0" max={points.length - 1} value={index} onChange={event => setSelected(Number(event.target.value))} /></label><p className="chart-reading">{mode === 'percent' ? `以 ${points[0].date} 已有净值为 0% 起点，不含分红再投资。${!data.complete ? '当前历史不完整，仅展示已有数据涨跌。' : ''}` : '单位：元 / 份。'}{points[index].dividend_note && ` · ${points[index].dividend_note}`}</p></>
}
