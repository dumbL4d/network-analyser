import type {
  DeviceOut,
  DeviceStatusDTO,
  HistorySampleOut,
} from '@/types/device'

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`)
  if (!response.ok) {
    throw new Error(
      `GET ${path} failed: ${response.status} ${response.statusText}`,
    )
  }
  return (await response.json()) as T
}

export async function fetchDevices(): Promise<DeviceOut[]> {
  return requestJson<DeviceOut[]>('/api/devices')
}

export async function fetchDeviceHistory(
  deviceId: string,
): Promise<HistorySampleOut[]> {
  return requestJson<HistorySampleOut[]>(`/api/history/${deviceId}`)
}

export function subscribeToStatusStream(
  onUpdate: (data: Record<string, DeviceStatusDTO>) => void,
  onError?: (err: Event) => void,
): () => void {
  const eventSource = new EventSource(`${API_BASE_URL}/api/stream/status`)

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
