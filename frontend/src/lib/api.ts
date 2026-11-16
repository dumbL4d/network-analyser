import type { AuditPage } from '@/types/audit'
import type { ChaosState } from '@/types/chaos'
import type {
  AnomalyEvent,
  DeviceCreate,
  DeviceOut,
  DeviceStatusDTO,
  DeviceUpdate,
  FlapCountOut,
  HistorySampleOut,
  HistoryWindow,
  HistoryWindowOut,
} from '@/types/device'
import type { HealthOut } from '@/types/health'
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
import type { LinkOut, SpofOut, WhatIfResult } from '@/types/topology'
import type {
  PasswordChangeRequest,
  UserCreate,
  UserOut,
} from '@/types/user'

// Vite env vars are compile-time (embedded into the static JS bundle at build
// time -- a plain SPA has no runtime environment to read from), so the Docker
// image bakes VITE_API_BASE_URL in via a build ARG. The default keeps the
// local `npm run dev` workflow working without any configuration.
// See frontend/.env.example for deployment guidance.
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8410'

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

// Two answers of the backend concern the whole session, not the one request
// that got them. They are announced on `window`, and AuthContext listens:
//  - 401: the session is over (the token expired, or the account is gone);
//  - 403 with code "password_change_required": a seeded password has to be
//    replaced before anything else is allowed.
export const SESSION_EXPIRED_EVENT = 'na:session-expired'
export const PASSWORD_CHANGE_REQUIRED_EVENT = 'na:password-change-required'

/**
 * Pull the backend's human-readable message out of an error response body.
 *
 * FastAPI raises three shapes:
 *  - ``{"detail": "<string>"}`` for HTTPException-detail messages (the vast
 *    majority of the 4xx we care about, e.g. "Cannot delete 'sw-ot': it has 5
 *    downstream device(s)...")
 *  - ``{"detail": [{"msg": "...", "loc": [...]}, ...]}`` for Pydantic
 *    validation errors (e.g. the invalid device type).
 *  - ``{"detail": {"code": "...", "message": "..."}}`` where the frontend has
 *    to tell the cases apart (the forced password change).
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
    if (typeof detail === 'object' && detail !== null && 'message' in detail) {
      return String(detail.message)
    }
  }
  return `${fallback} (HTTP ${response.status})`
}

/** The ``code`` of a ``{"detail": {"code": ...}}`` error body, if it has one. */
function errorCode(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail
  return typeof detail === 'object' && detail !== null && 'code' in detail
    ? String(detail.code)
    : null
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
  /** Gives the request up when it fires, e.g. `AbortSignal.timeout(ms)`. */
  signal?: AbortSignal
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
    signal: options.signal,
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
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
      throw new UnauthorizedError()
    }
    if (
      response.status === 403 &&
      errorCode(body) === 'password_change_required'
    ) {
      window.dispatchEvent(new Event(PASSWORD_CHANGE_REQUIRED_EVENT))
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

// --- Topology / monitoring ---------------------------------------------------

// A backend that accepts the connection and then never answers (frozen, or
// its event loop stuck) must not pass for one that is fine.
const HEALTH_TIMEOUT_MS = 20_000

/** Public: whether the API answers and the poll loop behind it keeps up. */
export function fetchHealth(): Promise<HealthOut> {
  return request<HealthOut>('/api/health', {
    signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
  })
}

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

// --- Incidents / playbooks ----------------------------------------------------

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

/** A single-use ticket that opens the status stream once, within 30 s. */
function fetchStreamTicket(): Promise<{ ticket: string; expires_in: number }> {
  return request('/api/stream/ticket', { method: 'POST', authenticated: true })
}

const STREAM_RETRY_MIN_MS = 1_000
const STREAM_RETRY_MAX_MS = 30_000

/**
 * Follow the live device statuses until the returned function is called.
 *
 * EventSource cannot set an Authorization header, and the login token must
 * not travel in a URL (URLs end up in logs and in the browser history). So
 * every connection is opened with a ticket: short-lived, good for one
 * connection, and fetched with the normal Authorization header.
 *
 * For the same reason EventSource's own reconnecting is not used: it would
 * come back with the URL it already has, whose ticket is used up. When the
 * connection drops it is closed, and a new one is opened with a new ticket,
 * after 1 s, 2 s, 4 s ... (at most 30 s) while it keeps failing.
 */
export function subscribeToStatusStream(
  onUpdate: (data: Record<string, DeviceStatusDTO>) => void,
  onError?: (err: Event) => void,
): () => void {
  // Without a token there is nothing to get a ticket with.
  if (getStoredToken() === null) {
    return () => {}
  }

  let eventSource: EventSource | null = null
  let retryTimer: number | undefined
  let failures = 0
  let stopped = false

  const handleMessage = (event: MessageEvent<string>) => {
    failures = 0 // the connection works: the next retry starts at 1 s again
    try {
      onUpdate(JSON.parse(event.data) as Record<string, DeviceStatusDTO>)
    } catch (err) {
      console.error('Failed to parse status stream message', err)
    }
  }

  const retryLater = () => {
    if (stopped) return
    const delay = Math.min(STREAM_RETRY_MIN_MS * 2 ** failures, STREAM_RETRY_MAX_MS)
    failures += 1
    retryTimer = window.setTimeout(connect, delay)
  }

  const connect = () => {
    fetchStreamTicket()
      .then(({ ticket }) => {
        if (stopped) return
        const source = new EventSource(
          `${API_BASE_URL}/api/stream/status?ticket=${encodeURIComponent(ticket)}`,
        )
        eventSource = source
        // The backend emits named "status" events, so the browser dispatches
        // them as "status" (not the default "message") and onmessage alone
        // would never fire. We register for both so the subscription works
        // either way.
        source.onmessage = handleMessage
        source.addEventListener('status', handleMessage as EventListener)
        source.onerror = (err) => {
          source.close()
          onError?.(err)
          retryLater()
        }
      })
      .catch((err: unknown) => {
        // A 401 means the session is over: the app is logging out, and a new
        // ticket would be refused too. Anything else (the backend is
        // restarting, the network is down) is worth another try.
        if (!(err instanceof UnauthorizedError)) retryLater()
      })
  }

  connect()

  return () => {
    stopped = true
    window.clearTimeout(retryTimer)
    eventSource?.close()
  }
}

// --- Settings -----------------------------------------------------------------

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

// --- Device CRUD --------------------------------------------------------------

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

// --- Extra links and topology analysis ---------------------------------------

/** Every extra link between devices (the dashed edges of the topology). */
export function fetchLinks(): Promise<LinkOut[]> {
  return request<LinkOut[]>('/api/links', { authenticated: true })
}

/** Link two devices (admin). The order of the two ids does not matter. */
export function createLink(
  deviceAId: string,
  deviceBId: string,
): Promise<LinkOut> {
  return request<LinkOut>('/api/links', {
    method: 'POST',
    authenticated: true,
    body: { device_a_id: deviceAId, device_b_id: deviceBId },
  })
}

export function deleteLink(linkId: number): Promise<void> {
  return request<void>(`/api/links/${linkId}`, {
    method: 'DELETE',
    authenticated: true,
  })
}

/** Single points of failure, largest blast radius first. */
export function fetchSpof(): Promise<SpofOut[]> {
  return request<SpofOut[]>('/api/analysis/spof', { authenticated: true })
}

/** What would happen if these devices failed? Changes nothing on the server. */
export function runWhatIf(failedDeviceIds: string[]): Promise<WhatIfResult> {
  return request<WhatIfResult>('/api/analysis/what-if', {
    method: 'POST',
    authenticated: true,
    body: { failed_device_ids: failedDeviceIds },
  })
}

// --- Fault injection (admin; docs/chaos.md) ----------------------------------
// Every action answers with the faults in place afterwards. When the chaos
// agent is not running the backend answers 503, and its message says what to
// do; it reaches the UI as the thrown Error's message.

export function fetchChaosState(): Promise<ChaosState> {
  return request<ChaosState>('/api/chaos/state', { authenticated: true })
}

/** Fail devices; everything they cut off is made unreachable as well. */
export function chaosFail(deviceIds: string[]): Promise<ChaosState> {
  return request<ChaosState>('/api/chaos/fail', {
    method: 'POST',
    authenticated: true,
    body: { device_ids: deviceIds },
  })
}

/** Slow a device down: delay and jitter in ms, packet loss in percent. */
export function chaosDegrade(
  deviceId: string,
  delayMs: number,
  jitterMs: number,
  lossPct: number,
): Promise<ChaosState> {
  return request<ChaosState>('/api/chaos/degrade', {
    method: 'POST',
    authenticated: true,
    body: {
      device_id: deviceId,
      delay_ms: delayMs,
      jitter_ms: jitterMs,
      loss_pct: lossPct,
    },
  })
}

export function chaosScenario(name: string): Promise<ChaosState> {
  return request<ChaosState>(`/api/chaos/scenario/${name}`, {
    method: 'POST',
    authenticated: true,
  })
}

/** Start every simulated device and remove every slowdown. Safe to repeat. */
export function chaosRestoreAll(): Promise<ChaosState> {
  return request<ChaosState>('/api/chaos/restore-all', {
    method: 'POST',
    authenticated: true,
  })
}

// --- Anomalies (advisory) -------------------------------------------------------

/** The most recent anomaly events, newest first; of one device if given. */
export function fetchAnomalies(
  params: { deviceId?: string; limit?: number } = {},
): Promise<AnomalyEvent[]> {
  const query = new URLSearchParams()
  if (params.deviceId) query.set('device_id', params.deviceId)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return request<AnomalyEvent[]>(`/api/anomalies${suffix}`, {
    authenticated: true,
  })
}

// --- Audit log (admin) --------------------------------------------------------

/** One page of the audit log, newest first. Both filters are exact matches. */
export function fetchAudit(
  params: {
    actor?: string
    action?: string
    limit?: number
    offset?: number
  } = {},
): Promise<AuditPage> {
  const query = new URLSearchParams()
  if (params.actor) query.set('actor', params.actor)
  if (params.action) query.set('action', params.action)
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return request<AuditPage>(`/api/audit${suffix}`, { authenticated: true })
}

// --- User management ----------------------------------------------------------

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