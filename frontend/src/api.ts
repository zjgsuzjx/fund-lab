export type Fund = {
  code: string; name: string; category: string; nav_date: string | null;
  unit_nav: string | null; source_observed_at: string; is_sample: boolean; trade_enabled: boolean;
}
export type FundPage = { items: Fund[]; total: number; page: number; page_size: number }
export type Health = { status: string; database: string; schema: string; fund_count: number }

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000) })
  if (!response.ok) throw new Error(response.status === 503 ? '数据库尚未就绪，请检查 PostgreSQL 服务并运行数据库迁移。' : '服务暂时不可用，请稍后重试。')
  return response.json() as Promise<T>
}
