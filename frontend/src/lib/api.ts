import type {
  DeviceCreate,
  DeviceOut,
  DeviceStatusDTO,
  DeviceUpdate,
  FlapCountOut,
  HistorySampleOut,
} from '@/types/device'
import type { AppSettingsOut, SettingsUpdate } from '@/types/settings'
import type {
  PasswordChangeRequest,
  UserCreate,
  UserOut,
} from '@/types/user'

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

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

export function fetchFlapCounts(): Promise<FlapCountOut[]> {
  return request<FlapCountOut[]>('/api/flaps', { authenticated: true })
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