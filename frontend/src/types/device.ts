export type DeviceStatus = 'healthy' | 'degraded' | 'down' | 'unknown'

export interface DeviceStatusDTO {
  status: DeviceStatus
  latency_ms: number | null
  timestamp: string
}

export interface DeviceOut {
  id: string
  name: string
  type: string
  ip: string
  zone: string
  parent_id: string | null
  ping_port: number
  notes: string
}

export interface HistorySampleOut {
  latency_ms: number | null
  timestamp: string
}
