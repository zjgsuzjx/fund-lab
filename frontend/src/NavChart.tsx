import { useEffect, useRef, useState } from 'react'
import type { NavHistory } from './api'

export default function NavChart({ data }: { data: NavHistory }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const points = data.items
  useEffect(() => { setSelected(null) }, [data])
  useEffect(() => {
    const element = canvas.current
    if (!element || !points.length) return
    const draw = () => {
      const width = element.clientWidth, height = 180, ratio = window.devicePixelRatio || 1
      element.width = width * ratio; element.height = height * ratio
      const ctx = element.getContext('2d')!
      ctx.scale(ratio, ratio)
      const values = points.map(p => Number(p.unit_nav)), low = Math.min(...values), high = Math.max(...values)
      const pad = Math.max((high - low) * .12, low * .0001), min = low - pad, max = high + pad
      const left = 49, right = width - 8, top = 14, bottom = 145
      const dates = points.map(p => Date.parse(p.date)), start = dates[0], end = dates[dates.length - 1]
      const x = (i: number) => end === start ? (left + right) / 2 : left + (dates[i] - start) / (end - start) * (right - left)
      const y = (v: number) => bottom - (v - min) / (max - min) * (bottom - top)
      ctx.font = '10px "Microsoft YaHei",sans-serif'; ctx.fillStyle = '#64748b'; ctx.strokeStyle = '#e4eaf3'; ctx.lineWidth = 1
      for (let i = 0; i < 3; i++) { const value = min + (max - min) * i / 2; const yy = y(value); ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(right, yy); ctx.stroke(); ctx.fillText(value.toFixed(4), 0, yy + 3) }
      ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(x(i), y(Number(p.unit_nav))) : ctx.moveTo(x(i), y(Number(p.unit_nav))))
      ctx.lineTo(x(points.length - 1), bottom); ctx.lineTo(x(0), bottom); ctx.closePath(); ctx.fillStyle = '#eaf2ff'; ctx.fill()
      ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(x(i), y(Number(p.unit_nav))) : ctx.moveTo(x(i), y(Number(p.unit_nav))))
      ctx.strokeStyle = '#1768e8'; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke()
      const index = selected ?? (points.length === 1 ? 0 : null)
      if (index !== null && points[index]) {
        ctx.beginPath(); ctx.arc(x(index), y(values[index]), 3.5, 0, Math.PI * 2); ctx.fillStyle = '#1768e8'; ctx.fill()
        ctx.beginPath(); ctx.moveTo(x(index), top); ctx.lineTo(x(index), bottom); ctx.strokeStyle = '#9bbef5'; ctx.lineWidth = 1; ctx.stroke()
      }
      ctx.fillStyle = '#64748b'; ctx.fillText(points[0].date, left, 168); ctx.textAlign = 'right'; ctx.fillText(points[points.length - 1].date, right, 168)
    }
    const observer = new ResizeObserver(draw); observer.observe(element); draw()
    return () => observer.disconnect()
  }, [points, selected])
  if (!points.length) return <div className="chart-empty">暂无可显示的净值数据</div>
  return <><canvas ref={canvas} className="nav-canvas" role="img" aria-label={`单位净值走势，从 ${points[0].date} 至 ${points[points.length - 1].date}，共 ${points.length} 个数据点。可使用下方滑块查看具体日期。`} onPointerMove={event => {
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - 49) / (rect.width - 57)))
    const target = Date.parse(points[0].date) + ratio * (Date.parse(points[points.length - 1].date) - Date.parse(points[0].date))
    let nearest = 0
    points.forEach((point, index) => { if (Math.abs(Date.parse(point.date) - target) < Math.abs(Date.parse(points[nearest].date) - target)) nearest = index })
    setSelected(nearest)
  }} /><label className="chart-slider"><span className="sr-only">选择净值日期</span><input aria-label="选择净值日期" type="range" min="0" max={points.length - 1} value={selected ?? points.length - 1} onChange={event => setSelected(Number(event.target.value))} /></label><p className="chart-reading" aria-live="polite">{points[selected ?? points.length - 1].date} · 单位净值 {Number(points[selected ?? points.length - 1].unit_nav).toFixed(4)}{points[selected ?? points.length - 1].dividend_note && ` · ${points[selected ?? points.length - 1].dividend_note}`}</p></>
}
