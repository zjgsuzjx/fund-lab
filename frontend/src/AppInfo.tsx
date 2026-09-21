import { useEffect, useState } from 'react'
import { api } from './api'

export default function AppInfo() {
  const [version, setVersion] = useState('读取中…')
  useEffect(() => {
    const controller = new AbortController()
    api<{ version: string }>('/health/live', undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) setVersion(`v${result.version}`) })
      .catch(() => { if (!controller.signal.aborted) setVersion('暂不可用') })
    return () => controller.abort()
  }, [])
  return <section className="settings-card app-info" aria-label="应用信息">
    <details><summary>系统版本<span>{version} <span className="app-info-chevron" aria-hidden="true">›</span></span></summary>
      <p>当前运行版本：{version}。支持基金浏览、自选管理、模拟买卖和持仓收益记录，基金数据在服务运行期间自动分批更新。</p>
    </details>
    <details><summary>关于本应用<span>基金练习室 <span className="app-info-chevron" aria-hidden="true">›</span></span></summary>
      <p>基金练习室 · Fund Lab，让每一次练习都有迹可循。通过虚拟资金体验基金买卖、确认结算与收益变化，逐步理解交易规则。</p>
      <p>本应用为独立学习与模拟工具，与支付宝无关联。所有资金均为虚拟资金，不支持充值或提现；公开数据和模拟规则仅供练习，不构成投资建议。</p>
      <p>账户和练习记录保存在运行服务的数据库中。</p>
    </details>
  </section>
}
