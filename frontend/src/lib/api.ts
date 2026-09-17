export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type DeviceStatus = 'healthy' | 'degraded' | 'down' | 'unknown'

export interface DeviceStatusDTO {
  status: DeviceStatus
  latency_ms: number | null
  timestamp: string
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
