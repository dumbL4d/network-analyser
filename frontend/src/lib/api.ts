import type {
  DeviceCreate,
  DeviceOut,
  DeviceStatusDTO,
  DeviceUpdate,
  FlapCountOut,
  HistorySampleOut,
  HistoryWindow,
  HistoryWindowOut,
} from '@/types/device'
import type {
  AvailabilityOut,
  AvailabilityWindow,
  IncidentDetail,
  IncidentHistoryPage,
  IncidentOut,
  IncidentState,
  IncidentStats,
  PlaybookOut,
} from '@/types/incident'
import type { AppSettingsOut, SettingsUpdate } from '@/types/settings'
import type {
  PasswordChangeRequest,
  UserCreate,
  UserOut,
} from '@/types/user'

// Vite env vars are compile-time (embedded into the static JS bundle at build
// time -- a plain SPA has no runtime environment to read from), so the Docker
// image bakes VITE_API_BASE_URL in via a build ARG. The default keeps the
// local `npm run dev` workflow from every earlier ticket working unchanged.
// See frontend/.env.example for deployment guidance.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const TOKEN_STORAGE_KEY = 'na_token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

/** Thrown on an HTTP 401. Consuming code detects this to log the user out. */
export class UnauthorizedError extends Error {
  constructor() {
    super('UNAUTHORIZED')
    this.name = 'UnauthorizedError'
  }
}

/**
 * Pull the backend's human-readable message out of an error response body.
 *
 * FastAPI raises two shapes:
 *  - ``{"detail": "<string>"}`` for HTTPException-detail messages (the vast
 *    majority of the 4xx we care about, e.g. "Cannot delete 'sw-ot': it has 5
 *    downstream device(s)...")
 *  - ``{"detail": [{"msg": "...", "loc": [...]}, ...]}`` for Pydantic
 *    validation errors (e.g. the invalid device type).
 *
 * Passing the real message through to the UI is important for the admin panel,
 * so callers can display exactly what the backend said instead of a generic
 * "request failed" string.
 */
function extractErrorMessage(
  response: Response,
  body: unknown,
  fallback: string,
): string {
  const record = body as { detail?: unknown } | null
  if (record !== null && typeof record === 'object' && 'detail' in record) {
    const detail = record.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) =>
          typeof entry === 'object' && entry !== null && 'msg' in entry
            ? String((entry as { msg: unknown }).msg)
            : null,
        )
        .filter((message): message is string => message !== null)
      if (messages.length > 0) return messages.join('; ')
    }
  }
  return `${fallback} (HTTP ${response.status})`
}

interface RequestOptions {
  authenticated?: boolean
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  /**
   * Most 401s mean "session invalid/expired" -> throw UnauthorizedError.
   * A few endpoints return 401 for REJECTED CREDENTIALS (e.g. change-password
   * with a wrong current_password); there the backend detail message should
   * surface instead of triggering a session-expiry flow.
   */
  unauthorizedIsExpired?: boolean
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const token = getStoredToken()
  if (options.authenticated && token !== null) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      // Non-JSON error body; fall back to status text.
    }
    const message = extractErrorMessage(
      response,
      body,
      `Request to ${path} failed`,
    )
    if (response.status === 401 && (options.unauthorizedIsExpired ?? true)) {
      throw new UnauthorizedError()
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

// --- Topology / monitoring (Ticket 2.x) -------------------------------------

export function fetchDevices(): Promise<DeviceOut[]> {
  return request<DeviceOut[]>('/api/devices', { authenticated: true })
}

export function fetchDeviceHistory(
  deviceId: string,
): Promise<HistorySampleOut[]> {
  return request<HistorySampleOut[]>(`/api/history/${deviceId}`, {
    authenticated: true,
  })
}

/**
 * A longer time range, read from the database. The backend picks the
 * resolution (raw samples or min/avg/max buckets) and reports which it used.
 */
export function fetchDeviceHistoryWindow(
  deviceId: string,
  window: HistoryWindow,
): Promise<HistoryWindowOut> {
  return request<HistoryWindowOut>(
    `/api/history/${deviceId}?window=${window}`,
    { authenticated: true },
  )
}

export function fetchFlapCounts(): Promise<FlapCountOut[]> {
  return request<FlapCountOut[]>('/api/flaps', { authenticated: true })
}

// --- Incidents / playbooks (Ticket 5.2/5.3) ---------------------------------

/** Live root-cause/collateral incident list; re-evaluated by the backend per call. */
export function fetchIncidents(): Promise<IncidentOut[]> {
  return request<IncidentOut[]>('/api/incidents', { authenticated: true })
}

// --- Stored incidents, their timeline and statistics -------------------------

/** One page of stored incidents, most recently opened first. */
export function fetchIncidentHistory(
  params: {
    states?: IncidentState[]
    deviceId?: string
    limit?: number
    offset?: number
  } = {},
): Promise<IncidentHistoryPage> {
  const query = new URLSearchParams()
  for (const state of params.states ?? []) query.append('state', state)
  if (params.deviceId) query.set('device_id', params.deviceId)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return request<IncidentHistoryPage>(`/api/incidents/history${suffix}`, {
    authenticated: true,
  })
}

export function fetchIncident(incidentId: number): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/api/incidents/${incidentId}`, {
    authenticated: true,
  })
}

/** Admin only. A 409 means the incident is no longer open. */
export function acknowledgeIncident(
  incidentId: number,
): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/api/incidents/${incidentId}/acknowledge`, {
    method: 'POST',
    authenticated: true,
  })
}

/** Admin only. */
export function addIncidentNote(
  incidentId: number,
  text: string,
): Promise<IncidentDetail> {
  return request<IncidentDetail>(`/api/incidents/${incidentId}/notes`, {
    method: 'POST',
    authenticated: true,
    body: { text },
  })
}

export function fetchIncidentStats(): Promise<IncidentStats> {
  return request<IncidentStats>('/api/stats/incidents', { authenticated: true })
}

export function fetchAvailability(
  window: AvailabilityWindow,
): Promise<AvailabilityOut> {
  return request<AvailabilityOut>(`/api/stats/availability?window=${window}`, {
    authenticated: true,
  })
}

export function fetchPlaybook(
  deviceType: string,
  state: string,
): Promise<PlaybookOut> {
  return request<PlaybookOut>(
    `/api/playbooks/${encodeURIComponent(deviceType)}/${encodeURIComponent(state)}`,
    { authenticated: true },
  )
}

export function subscribeToStatusStream(
  onUpdate: (data: Record<string, DeviceStatusDTO>) => void,
  onError?: (err: Event) => void,
): () => void {
  // The backend's SSE endpoint authenticates via a `token` query parameter
  // (EventSource cannot set an Authorization header), so the stored JWT is
  // appended to the URL. Without a token there is nothing to authenticate with
  // and no connection should be attempted.
  const token = getStoredToken()
  if (token === null) {
    return () => {}
  }

  const eventSource = new EventSource(
    `${API_BASE_URL}/api/stream/status?token=${encodeURIComponent(token)}`,
  )

  const handleMessage = (event: MessageEvent<string>) => {
    try {
      onUpdate(JSON.parse(event.data) as Record<string, DeviceStatusDTO>)
    } catch (err) {
      console.error('Failed to parse status stream message', err)
    }
  }

  // The backend emits named "status" events, so the browser dispatches them as
  // "status" (not the default "message") and onmessage alone would never fire.
  // We register for both so the subscription works either way.
  eventSource.onmessage = handleMessage
  eventSource.addEventListener('status', handleMessage as EventListener)

  eventSource.onerror = (err) => {
    onError?.(err)
  }

  return () => {
    eventSource.removeEventListener('status', handleMessage as EventListener)
    eventSource.close()
  }
}

// --- Settings (Ticket 4.1) --------------------------------------------------

export function fetchSettings(): Promise<AppSettingsOut> {
  return request<AppSettingsOut>('/api/settings', { authenticated: true })
}

export function updateSettings(
  patch: SettingsUpdate,
): Promise<AppSettingsOut> {
  return request<AppSettingsOut>('/api/settings', {
    method: 'PATCH',
    authenticated: true,
    body: patch,
  })
}

// --- Device CRUD (Ticket 4.2) ------------------------------------------------

export function createDevice(data: DeviceCreate): Promise<DeviceOut> {
  return request<DeviceOut>('/api/devices', {
    method: 'POST',
    authenticated: true,
    body: data,
  })
}

export function updateDevice(
  deviceId: string,
  patch: DeviceUpdate,
): Promise<DeviceOut> {
  return request<DeviceOut>(`/api/devices/${deviceId}`, {
    method: 'PATCH',
    authenticated: true,
    body: patch,
  })
}

export function deleteDevice(deviceId: string): Promise<void> {
  return request<void>(`/api/devices/${deviceId}`, {
    method: 'DELETE',
    authenticated: true,
  })
}

// --- User management (Ticket 4.3) --------------------------------------------

export function fetchUsers(): Promise<UserOut[]> {
  return request<UserOut[]>('/api/users', { authenticated: true })
}

export function createUser(data: UserCreate): Promise<UserOut> {
  return request<UserOut>('/api/users', {
    method: 'POST',
    authenticated: true,
    body: data,
  })
}

export function deleteUser(userId: number): Promise<void> {
  return request<void>(`/api/users/${userId}`, {
    method: 'DELETE',
    authenticated: true,
  })
}

export function changePassword(
  data: PasswordChangeRequest,
): Promise<{ detail: string }> {
  // 401 here means the CURRENT password was wrong, not that the session
  // expired -- so propagate the backend's message instead of UnauthorizedError.
  return request<{ detail: string }>('/api/auth/change-password', {
    method: 'PATCH',
    authenticated: true,
    body: data,
    unauthorizedIsExpired: false,
  })
}