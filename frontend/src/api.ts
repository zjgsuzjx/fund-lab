export type Fund = {
  code: string; name: string; category: string; category_group: string; share_class: string | null;
  nav_date: string | null; unit_nav: string | null; year_change: string | null; change_basis: string;
  source_observed_at: string; last_sync_at: string | null; is_sample: boolean; trade_enabled: boolean;
  is_watched: boolean; history_complete: boolean; trade_disabled_reason: string;
}
export type FundPage = { items: Fund[]; total: number; page: number; page_size: number }
export type Health = { status: string; database: string; schema: string; fund_count: number }
export type FundDetail = Fund & {
  simulation_rule?: SimulationRule;
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
export type Account = { id: string; available_cash: string; reserved_cash: string; redemption_cash: string; total_profit: string | null; total_assets: string | null; created_at: string }
export type Ledger = { items: { id: string; kind: string; amount: string; balance_after: string; available_delta: string; reserved_delta: string; reserved_after: string; redemption_delta: string; redemption_after: string; created_at: string }[] }
export type SimulationRule = { version: string; name: string; minimum: string; scope: string; sources: { url: string; published_on: string; pages?: string }[] }
export type BuyQuote = { fund_code: string; fund_name: string; amount: string; fee: string; net_amount: string;
  fee_label: string; available_cash: string; trade_date: string; confirmation_date: string; cancel_until: string;
  rule_version: string; rule: SimulationRule }
export type BuyRequest = { fund_code: string; amount: string; request_key: string; rule_version: string; trade_date: string }
export type Order = { kind: 'buy'; id: string; fund_code: string; fund_name: string; status: 'pending' | 'confirmed' | 'cancelled';
  amount: string; fee: string; net_amount: string; trade_date: string; confirmation_date: string; cancel_until: string;
  can_cancel: boolean; confirmed_nav: string | null; shares: string | null; created_at: string; completed_at: string | null;
  rule: SimulationRule; wait_reason: string }
export type Orders = { items: (Order | SellOrder)[]; total: number; page: number; page_size: number }
export type Portfolio = { items: { fund_code: string; fund_name: string; shares: string; cost: string;
  frozen_shares: string; available_shares: string; sell_disabled_reason: string; holding_profit: string | null; market_value: string | null; nav_date: string | null; unit_nav: string | null;
  lots: { order_id: string; shares: string; frozen_shares: string; cost: string; confirmation_date: string }[] }[];
  available_cash: string; reserved_cash: string; redemption_cash: string; total_profit: string | null; total_assets: string | null; market_value: string | null; holding_profit: string | null; realized_profit: string; valuation_note: string }
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

export type SellContext = { fund_code: string; fund_name: string; total_shares: string; available_shares: string;
  frozen_shares: string; locked_shares: string; reference_nav: string | null; reference_date: string | null;
  trade_date: string | null; confirmation_date: string | null; arrival_date: string | null;
  cancel_until: string | null; disabled_reason: string; rule: SimulationRule }
export type SellQuote = SellContext & { shares: string; gross_amount: string; fee: string; net_amount: string;
  quote_token: string; allocations: { lot_id: string; buy_order_id: string; shares: string;
    confirmation_date: string; holding_days: number; fee_rate: string; gross_amount: string; fee: string; net_amount: string }[] }
export type SellRequest = { fund_code: string; shares: string; request_key: string; quote_token: string }
export type SellOrder = { id: string; kind: 'sell'; fund_code: string; fund_name: string;
  status: 'pending' | 'confirmed' | 'paid' | 'cancelled'; shares: string; trade_date: string;
  confirmation_date: string; arrival_date: string; cancel_until: string; can_cancel: boolean;
  created_at: string; confirmed_at: string | null; paid_at: string | null; completed_at: string | null;
  rule: SimulationRule; quote: SellQuote; wait_reason: string; confirmed_nav: string | null;
  gross_amount: string | null; fee: string | null; net_amount: string | null; realized_profit: string | null;
  allocations: { lot_id: string; shares: string; holding_days: number; fee_rate: string; cost: string | null; fee: string | null }[] }
