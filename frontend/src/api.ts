export type Fund = {
  code: string; name: string; category: string; category_group: string; share_class: string | null;
  nav_date: string | null; unit_nav: string | null; year_change: string | null; change_basis: string;
  source_observed_at: string; last_sync_at: string | null; is_sample: boolean; trade_enabled: boolean;
  is_watched: boolean; history_complete: boolean; trade_disabled_reason: string;
}
export type FundPage = { items: Fund[]; total: number; page: number; page_size: number }
export type Health = { status: string; database: string; schema: string; fund_count: number }
export type FundDetail = Fund & {
  source_url: string; nav_source_url: string; earliest_nav_date: string | null; history_count: number;
  rules: { status: string; source_url: string; observed_at: string | null; is_snapshot: boolean;
    subscription_fees: string[][]; redemption_fees: string[][]; ongoing_fees: string[][];
    minimum_purchase: string | null; confirmation: string | null; arrival: string | null; note: string };
}
export type NavHistory = { items: { date: string; unit_nav: string; dividend_note: string | null }[];
  period: string; complete: boolean; change: string | null; message: string; basis: string; end_date?: string }
export type SyncRuns = { items: { id: string; fund_code: string; status: string; started_at: string;
  finished_at: string | null; inserted: number; unchanged: number; message: string }[] }
export type User = { id: string; username: string; created_at: string }
export type Account = { id: string; available_cash: string; created_at: string }
export type Ledger = { items: { id: string; kind: string; amount: string; balance_after: string; created_at: string }[] }
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}
export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-Fund-Lab': '1' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
    })
  } catch { throw new Error('连接超时或服务未启动，请稍后重试。') }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new ApiError(response.status, typeof data.detail === 'string' ? data.detail : '请求参数有误，请检查后重试。')
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return api<T>(path.replace(/^\/api/, ''), undefined, signal)
}
