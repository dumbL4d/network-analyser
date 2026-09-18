import type {
  DeviceOut,
  DeviceStatusDTO,
  HistorySampleOut,
} from '@/types/device'

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

async function requestJson<T>(
  path: string,
  options: { authenticated?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getStoredToken()
  if (options.authenticated && token !== null) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { headers })
  if (!response.ok) {
    if (response.status === 401) {
      throw new UnauthorizedError()
    }
    throw new Error(
      `GET ${path} failed: ${response.status} ${response.statusText}`,
    )
  }
  return (await response.json()) as T
}

export async function fetchDevices(): Promise<DeviceOut[]> {
  return requestJson<DeviceOut[]>('/api/devices', { authenticated: true })
}

export async function fetchDeviceHistory(
  deviceId: string,
): Promise<HistorySampleOut[]> {
  return requestJson<HistorySampleOut[]>(`/api/history/${deviceId}`, {
    authenticated: true,
  })
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