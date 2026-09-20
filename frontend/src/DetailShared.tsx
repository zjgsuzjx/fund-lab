import type { ReactNode } from 'react'

export function TradeReceipt({ status, title, label, amount, fund, code, children }: {
  status: string; title: string; label: string; amount: string; fund: string; code: string; children?: ReactNode;
}) {
  return <section className={`trade-receipt receipt-${status}`}>
    <div className="receipt-state"><img src={`/assets/${status === 'pending' ? 'clock-3' : 'notebook-pen'}.svg`} alt="" /><span>{title}</span><small>模拟交易</small></div>
    <p className="receipt-label">{label}</p><strong className="receipt-amount">{amount}</strong>
    <a className="receipt-fund" href={`#fund/${code}?return=orders`}><span>{fund}</span><small>{code} · 查看基金</small></a>
    {children && <div className="receipt-note">{children}</div>}
  </section>
}

export function TradeTimeline({ steps, cancelled }: { steps: { title: string; detail: string; complete: boolean }[]; cancelled: boolean }) {
  return <section className="trade-card timeline-card"><h2>交易进度</h2>
    {cancelled ? <p className="cancelled-note">申请已撤销，后续确认流程已停止。</p> : null}
    <ol className="trade-timeline">{steps.map((step, index) => <li key={index} className={step.complete ? 'is-complete' : cancelled ? 'is-stopped' : 'is-waiting'}><span className="step-number">{index + 1}</span><div><strong>{step.title}</strong><p>{step.detail}</p></div></li>)}</ol>
  </section>
}

export function OrderReference({ id, created }: { id: string; created: string }) {
  return <details className="order-reference"><summary>订单信息<span>编号与申请时间</span></summary><dl><dt>订单编号</dt><dd>{id}</dd><dt>申请时间</dt><dd>{created}（北京时间）</dd></dl></details>
}
