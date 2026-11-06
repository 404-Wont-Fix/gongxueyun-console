/* Tiny typed API client with a single place for auth + error shaping. */

const TOKEN_KEY = 'gxy.token'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export interface User {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'user'
  is_active: boolean
}

export interface Account {
  id: number
  owner_id: number
  label: string
  phone: string
  enabled: boolean
  auto_clock_in: boolean
  auto_reports: boolean
  device: Record<string, unknown>
  location: Record<string, unknown>
  coord_type: 'gcj02' | 'wgs84'
  profile: Record<string, string>
  morning_enabled: boolean
  morning_time: string
  evening_enabled: boolean
  evening_time: string
  weekdays: string
  calendar_enabled: boolean
  report_time: string
  report_types: string
  mirror_attendence_time: boolean
  has_session: boolean
  session_updated_at: string | null
  plan: { planId?: string; planName?: string; startTime?: string; endTime?: string }
  plan_updated_at: string | null
  job: Record<string, unknown>
  last_status: string
  last_message: string
  last_run_at: string | null
  notify: Record<string, string>
}

export interface Execution {
  id: number
  account_id: number
  account_label: string
  kind: string
  subtype: string
  trigger: string
  status: string
  message: string
  target_date: string
  detail: Record<string, unknown>
  created_at: string
  finished_at: string | null
  duration_ms: number
}

export interface Verification {
  id: string
  account_id: number
  account_label: string
  kind: 'START' | 'END' | 'HOLIDAY'
  target_date: string
  verification_type: 'account' | 'face' | 'captcha'
  state: string
  verification_confirmed: boolean
  record_confirmed: boolean
  resume_attempted: boolean
  resume_state: string
  attempts: number
  server_time: string
  created_at: string | null
  expires_at: number
  last_checked_at: number
  has_link: boolean
  link: string
  browser_link: string
  captcha: { image: string; words: string[]; ready: boolean } | null
  note: string
  can_resume: boolean
}

export interface CalendarPlan {
  account_id: number
  account_label: string
  mode: 'work' | 'holiday' | 'skip' | 'unknown'
  source: string
  reason: string
  automatic: boolean
  slots: Array<{ kind: string; time: string }>
}
export interface CalendarDay {
  date: string
  weekday: number
  day_type: 'normal' | 'holiday' | 'makeup' | 'unknown'
  name: string
  is_today: boolean
  stats: { expected: number; confirmed: number; pending: number; failed: number; remaining: number; attempts: number }
  plans: CalendarPlan[]
  records: Array<{ account_id: number; account_label: string; attendance_id: string; kind: string; time: string; state: string; address: string }>
  executions: Array<{ id: number; account_id: number; account_label: string; kind: string; status: string; message: string; time: string }>
}
export interface CalendarData {
  month: string
  today: string
  calendar: {
    year: number; status: string; has_cache: boolean; message: string; checked_at: string | null; accepted_at: string | null
    sources: Record<string, { status: string; urls: string[]; error?: string; days?: number }>
  }
  days: CalendarDay[]
  stats: { expected: number; confirmed: number; pending: number; failed: number; attempts: number }
  accounts: Array<{ id: number; label: string }>
  record_sync: Array<{ account_id: number; synced_at: string }>
}

export interface Overview {
  today: string
  accounts: number
  enabled_accounts: number
  auto_accounts: number
  counts: Record<string, number>
  pending_verifications: number
  per_account: Array<{
    id: number
    label: string
    enabled: boolean
    auto_clock_in: boolean
    last_status: string
    last_message: string
    today: Array<{ kind: string; status: string; message: string; time: string | null }>
  }>
  recent: Execution[]
}

export interface ReportDraft {
  id: number
  account_id: number
  report_type: 'day' | 'week' | 'month' | 'summary'
  title: string
  content: string
  period_start: string
  period_end: string
  yearmonth: string
  weeks: string
  status: 'draft' | 'submitted' | 'failed'
  remote_report_id: string
  error: string
  created_at: string | null
  submitted_at: string | null
  form_fields: Array<Record<string, unknown>>
  plan_id: number | null
  plan_date: string
}

export interface PlanItem {
  index: number
  date: string
  theme: string
  tasks: string[]
  key_points: string
  draft: { draft_id: number; status: string; title: string } | null
}

export interface WritingPlan {
  id: number
  account_id: number
  kind: 'week' | 'month'
  start_date: string
  end_date: string
  title: string
  source: 'ai' | 'template' | 'manual'
  status: 'active' | 'archived'
  items: PlanItem[]
  created_at: string | null
  progress: { total: number; drafted: number; submitted: number }
}

export interface AISettings {
  base_url: string
  model: string
  temperature: number
  timeout: number
  configured: boolean
  source: string
  has_key: boolean
}

export interface MapConfig {
  tile_url: string
  attribution: string
  subdomains: string
  tile_coord: 'wgs84' | 'gcj02'
  geocoder: string
  has_amap_key: boolean
}

export interface MapSettings {
  provider: 'osm' | 'amap'
  has_amap_key: boolean
  geocode_base_url: string
  tile_url: string
  tile_subdomains: string
  tile_coord: 'wgs84' | 'gcj02'
  attribution: string
  source: string
}

export interface GeoResult {
  label: string
  lat: number
  lng: number
  coord: 'wgs84' | 'gcj02'
  type?: string
  province?: string
  city?: string
  area?: string
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(`/api${path}`, { ...options, headers })
  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }
  if (response.status === 401) {
    setToken(null)
    window.dispatchEvent(new CustomEvent('gxy:unauthorized'))
  }
  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `请求失败（HTTP ${response.status}）`
    throw new ApiError(detail, response.status)
  }
  return payload as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),

  login: (username: string, password: string) =>
    request<{ access_token: string; user: User }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  me: () => request<User>('/auth/me'),

  accounts: () => request<Account[]>('/accounts'),
  createAccount: (body: unknown) => request<Account>('/accounts', { method: 'POST', body: JSON.stringify(body) }),
  updateAccount: (id: number, body: unknown) =>
    request<Account>(`/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteAccount: (id: number) => request<{ message: string }>(`/accounts/${id}`, { method: 'DELETE' }),
  probeAccount: (id: number) => request<Record<string, unknown>>(`/accounts/${id}/login`, { method: 'POST' }),
  refreshPlan: (id: number) => request<Record<string, unknown>>(`/accounts/${id}/plan`, { method: 'POST' }),

  records: (id: number, month?: string) =>
    request<{ month: string; range: string[]; records: Array<Record<string, string>> }>(
      `/accounts/${id}/records${month ? `?month=${month}` : ''}`,
    ),
  clockIn: (id: number, kind: 'START' | 'END' | 'HOLIDAY', options: { replace?: boolean; when?: string } = {}) =>
    request<{ status: string; message: string; session_id?: string | null }>(`/accounts/${id}/clock-in`, {
      method: 'POST',
      body: JSON.stringify({ kind, replace: !!options.replace, ...(options.when ? { when: options.when } : {}) }),
    }),

  calendar: (month: string, accountId?: number) => request<CalendarData>(`/calendar?month=${encodeURIComponent(month)}${accountId ? `&account_id=${accountId}` : ''}`),
  syncCalendar: (year: number) => request<CalendarData['calendar']>(`/calendar/sync?year=${year}`, { method: 'POST' }),
  syncCalendarRecords: (id: number, month: string) => request(`/calendar/records/${id}/sync?month=${encodeURIComponent(month)}`, { method: 'POST' }),
  setCalendarOverride: (id: number, day: string, mode: string, note: string) => request(`/calendar/overrides/${id}/${day}`, { method: 'PUT', body: JSON.stringify({ mode, note }) }),
  clearCalendarOverride: (id: number, day: string) => request(`/calendar/overrides/${id}/${day}`, { method: 'DELETE' }),

  overview: () => request<Overview>('/overview'),
  executions: (params: { account_id?: number; status?: string; limit?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.account_id) query.set('account_id', String(params.account_id))
    if (params.status) query.set('status', params.status)
    query.set('limit', String(params.limit ?? 50))
    return request<{ items: Execution[]; total: number }>(`/executions?${query.toString()}`)
  },

  verifications: () => request<Verification[]>('/verifications'),
  checkVerification: (id: string) => request<Verification>(`/verifications/${id}/check`, { method: 'POST' }),
  confirmVerification: (id: string) =>
    request<{ status: string; message?: string; view: Verification }>(`/verifications/${id}/confirm`, { method: 'POST' }),
  submitCaptcha: (id: string, points: Array<{ x: number; y: number }>) =>
    request<{ result: { status: string; message: string }; session: Verification }>(`/verifications/${id}/captcha`, {
      method: 'POST',
      body: JSON.stringify({ points }),
    }),
  refreshCaptcha: (id: string) =>
    request<{ image: string; words: string[]; ready: boolean }>(`/verifications/${id}/captcha/refresh`, { method: 'POST' }),
  dismissVerification: (id: string) => request<Verification>(`/verifications/${id}/dismiss`, { method: 'POST' }),

  reports: (id: number, type: string) =>
    request<{ type: string; items: Array<Record<string, unknown>> }>(`/accounts/${id}/reports?type=${type}`),
  drafts: (id: number) => request<ReportDraft[]>(`/accounts/${id}/drafts`),
  createDraft: (id: number, body: { report_type: string; day?: string; notes?: string; use_ai?: boolean }) =>
    request<ReportDraft>(`/accounts/${id}/drafts`, { method: 'POST', body: JSON.stringify(body) }),
  updateDraft: (id: number, body: { title?: string; content?: string }) =>
    request<ReportDraft>(`/drafts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  submitDraft: (id: number) =>
    request<{ status: string; message: string; draft: ReportDraft }>(`/drafts/${id}/submit`, { method: 'POST' }),
  deleteDraft: (id: number) => request<{ message: string }>(`/drafts/${id}`, { method: 'DELETE' }),

  plans: (accountId: number) => request<WritingPlan[]>(`/accounts/${accountId}/plans`),
  createPlan: (accountId: number, body: { kind: 'week' | 'month'; start_date?: string; notes?: string; use_ai?: boolean }) =>
    request<WritingPlan>(`/accounts/${accountId}/plans`, { method: 'POST', body: JSON.stringify(body) }),
  updatePlan: (planId: number, body: { title?: string; status?: 'active' | 'archived' }) =>
    request<WritingPlan>(`/plans/${planId}`, { method: 'PATCH', body: JSON.stringify(body) }),
  updatePlanItem: (planId: number, index: number, body: { theme?: string; tasks?: string[]; key_points?: string }) =>
    request<WritingPlan>(`/plans/${planId}/items/${index}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deletePlan: (planId: number) => request<{ message: string }>(`/plans/${planId}`, { method: 'DELETE' }),

  aiSettings: () => request<AISettings>('/settings/ai'),
  saveAISettings: (body: Record<string, unknown>) =>
    request<AISettings>('/settings/ai', { method: 'PUT', body: JSON.stringify(body) }),
  testAISettings: (body: Record<string, unknown>) =>
    request<{ ok: boolean; latency_ms?: number; reply?: string; message?: string }>('/settings/ai/test', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  clearAISettings: () => request<{ message: string }>('/settings/ai', { method: 'DELETE' }),

  mapConfig: () => request<MapConfig>('/map-config'),
  mapSettings: () => request<MapSettings>('/settings/map'),
  saveMapSettings: (body: Record<string, unknown>) =>
    request<MapSettings>('/settings/map', { method: 'PUT', body: JSON.stringify(body) }),
  testMapSettings: (body: Record<string, unknown>) =>
    request<{ ok: boolean; provider?: string; count?: number; sample?: unknown[]; latency_ms?: number; message?: string }>(
      '/settings/map/test',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  clearMapSettings: () => request<{ message: string }>('/settings/map', { method: 'DELETE' }),
  geoSearch: (q: string) => request<{ results: GeoResult[] }>(`/geo/search?q=${encodeURIComponent(q)}`),
  geoReverse: (lat: number, lng: number, coord: string) =>
    request<{ address: string; province: string; city: string; area: string; coord: string }>(
      `/geo/reverse?lat=${lat}&lng=${lng}&coord=${coord}`,
    ),

  capabilities: () =>
    request<{
      captcha: { slider_ready: boolean; clickword_ready: boolean; clickword_model_dir: string }
      package_version: string
      build_number: string
      code_version: string
      timezone: string
      scheduler_enabled: boolean
      ai_configured: boolean
      notify_channels: string[]
    }>('/capabilities'),
  settings: () => request<Record<string, unknown>>('/settings'),
  notifyTest: () => request<{ sent: string[]; message: string }>('/notify-test', { method: 'POST' }),
  changePassword: (old_password: string, new_password: string) =>
    request<{ message: string }>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ old_password, new_password }),
    }),
  users: () => request<User[]>('/auth/users'),
  createUser: (body: { username: string; password: string; role: string; display_name?: string }) =>
    request<User>('/auth/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: number, body: Record<string, unknown>) =>
    request<User>(`/auth/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
}
