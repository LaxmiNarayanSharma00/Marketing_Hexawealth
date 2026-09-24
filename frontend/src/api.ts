export type Session = {
  name: string
  status: string
  has_storage_state: boolean
  cookie_count: number
  created_at?: string
  updated_at?: string
}

export type LoginStatus = {
  session_name: string
  status: 'idle' | 'running' | 'done' | 'error'
  logs: string[]
  error: string | null
  session: Session | null
}

export type Source = {
  id: string
  source_kind: string
  source_kind_label: string
  type: string
  company: string
  link: string
  use_case: string
  created_at?: string
  updated_at?: string
}

export type AutomationRun = {
  id: string
  kind: string
  kind_label: string
  session_name: string
  company: string
  source_id: string
  source_link: string
  schedule_id?: string | null
  trigger?: 'manual' | 'schedule' | string
  max_connections: number
  max_requests?: number
  status: string
  logs: string[]
  error: string | null
  result?: {
    found?: number
    scraped?: number
    failed?: number
    skipped?: number
    selected?: number
    sent?: number
    engaged?: number
    sessions?: number
    sources?: number
    pairs?: number
    profile_ids?: string[]
  }
  created_at?: string
  updated_at?: string
}

export type Schedule = {
  id: string
  kind: string
  session_name: string
  source_id: string
  company: string
  source_link: string
  max_profiles: number
  source_ids?: string[]
  actions?: string[]
  run_time: string
  enabled: boolean
  last_run_at?: string | null
  last_run_id?: string | null
  last_run_status?: string | null
  last_error?: string | null
  fired_on_date?: string | null
  created_at?: string
  updated_at?: string
}

export type BrandSource = {
  id: string
  label: string
  url: string
}

export type Profile = {
  id: string
  linkedin_url: string
  name?: string
  location?: string
  about?: string
  current_job_title?: string
  current_company?: string
  open_to_work?: boolean
  experiences?: unknown[]
  educations?: unknown[]
  audience?: string
  source_company?: string
  source_id?: string
  automation_id?: string
  session_name?: string
  connection_status?: string
  connection_note?: string
  created_at?: string
  updated_at?: string
}

export type Audience = {
  source_id: string
  company: string
  audience: string
  source_link: string
  eligible: number
  total: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try {
      const j = JSON.parse(text)
      msg = j.detail || text
    } catch {
      /* keep text */
    }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return res.json() as Promise<T>
}

export const api = {
  listSessions: () => request<{ sessions: Session[] }>('/api/sessions'),
  createSession: (name: string) =>
    request<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  deleteSession: (name: string) =>
    request<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),
  startLogin: (name: string) =>
    request<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(name)}/login`, {
      method: 'POST',
    }),
  loginStatus: (name: string) =>
    request<LoginStatus>(
      `/api/sessions/${encodeURIComponent(name)}/login-status`,
    ),

  listSources: (sourceKind?: string) => {
    const q = sourceKind
      ? `?source_kind=${encodeURIComponent(sourceKind)}`
      : ''
    return request<{ sources: Source[] }>(`/api/sources${q}`)
  },
  createCompanyPeoplesSource: (body: {
    link: string
    company?: string
    type?: string
    use_case?: string
  }) =>
    request<Source>('/api/sources/company-peoples', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  createInfluencerSource: (body: {
    link: string
    company?: string
    type?: string
    use_case?: string
  }) =>
    request<Source>('/api/sources/influencer', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  createIndividualSource: (body: {
    link: string
    company?: string
    type?: string
    use_case?: string
  }) =>
    request<Source>('/api/sources/individual', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  deleteSource: (id: string) =>
    request<{ ok: boolean }>(`/api/sources/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  listAutomations: (kind?: string) => {
    const q = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    return request<{ runs: AutomationRun[] }>(`/api/automations${q}`)
  },
  getAutomation: (id: string) =>
    request<AutomationRun>(`/api/automations/${encodeURIComponent(id)}`),
  activateCompanyPeople: (body: {
    session_name: string
    source_id: string
    max_connections: number
  }) =>
    request<AutomationRun>('/api/automations/company-people', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  activateBuildConnection: (body: {
    session_name: string
    source_id: string
    max_requests: number
  }) =>
    request<AutomationRun>('/api/automations/build-connection', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  activateBrandEngage: (body: {
    session_name: string
    source_ids?: string[]
    actions?: string[]
  }) =>
    request<AutomationRun>('/api/automations/brand-engage', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listBrandSources: () =>
    request<{ sources: BrandSource[]; actions: string[] }>(
      '/api/brand-sources',
    ),
  listProfiles: (opts?: {
    source_company?: string
    source_id?: string
    automation_id?: string
  }) => {
    const params = new URLSearchParams()
    if (opts?.source_company) params.set('source_company', opts.source_company)
    if (opts?.source_id) params.set('source_id', opts.source_id)
    if (opts?.automation_id) params.set('automation_id', opts.automation_id)
    const q = params.toString() ? `?${params}` : ''
    return request<{ profiles: Profile[] }>(`/api/profiles${q}`)
  },
  listAudiences: () => request<{ audiences: Audience[] }>('/api/audiences'),

  listSchedules: (kind?: string) => {
    const q = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    return request<{ schedules: Schedule[] }>(`/api/schedules${q}`)
  },
  createCompanyPeopleSchedule: (body: {
    session_name: string
    source_id: string
    max_profiles: number
    run_time: string
    enabled?: boolean
  }) =>
    request<Schedule>('/api/schedules/company-people', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  createBuildConnectionSchedule: (body: {
    session_name: string
    source_id: string
    max_profiles: number
    run_time: string
    enabled?: boolean
  }) =>
    request<Schedule>('/api/schedules/build-connection', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  createBrandEngageSchedule: (body: {
    session_name: string
    source_ids: string[]
    actions: string[]
    run_time: string
    enabled?: boolean
  }) =>
    request<Schedule>('/api/schedules/brand-engage', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateSchedule: (
    id: string,
    body: {
      session_name?: string
      source_id?: string
      max_profiles?: number
      run_time?: string
      enabled?: boolean
      source_ids?: string[]
      actions?: string[]
    },
  ) =>
    request<Schedule>(`/api/schedules/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  startSchedule: (id: string) =>
    request<Schedule>(`/api/schedules/${encodeURIComponent(id)}/start`, {
      method: 'POST',
    }),
  pauseSchedule: (id: string) =>
    request<Schedule>(`/api/schedules/${encodeURIComponent(id)}/pause`, {
      method: 'POST',
    }),
  deleteSchedule: (id: string) =>
    request<{ ok: boolean }>(`/api/schedules/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
}

export async function pollLogin(
  name: string,
  onUpdate: (s: LoginStatus) => void,
): Promise<LoginStatus> {
  for (;;) {
    const status = await api.loginStatus(name)
    onUpdate(status)
    if (status.status === 'done' || status.status === 'error') return status
    await new Promise((r) => setTimeout(r, 1000))
  }
}

export async function pollAutomation(
  id: string,
  onUpdate: (s: AutomationRun) => void,
): Promise<AutomationRun> {
  for (;;) {
    const status = await api.getAutomation(id)
    onUpdate(status)
    if (status.status === 'done' || status.status === 'error') return status
    await new Promise((r) => setTimeout(r, 1200))
  }
}
