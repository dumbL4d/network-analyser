export type DeviceStatus = 'healthy' | 'degraded' | 'down' | 'unknown'

// The official set of device types, mirrored from the backend's Literal.
export const DEVICE_TYPES = [
  'firewall',
  'switch',
  'server',
  'plc',
  'hmi',
  'ap',
  'scanner',
] as const

export type DeviceType = (typeof DEVICE_TYPES)[number]

export interface DeviceStatusDTO {
  /** Confirmed (debounced) status. */
  status: DeviceStatus
  latency_ms: number | null
  timestamp: string
  /** The latest poll's raw result, before debouncing. */
  raw_status: DeviceStatus
  /** Polls in a row whose raw result was not healthy. */
  consecutive_failures: number
  /** Polls in a row whose raw result was healthy. */
  consecutive_successes: number
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

/** POST /api/devices body (backend DeviceCreate). */
export interface DeviceCreate {
  id: string
  name: string
  type: DeviceType
  ip: string
  zone: string
  parent_id?: string | null
  ping_port?: number
  notes?: string
}

/** PATCH /api/devices/{id} body (backend DeviceUpdate; id is immutable). */
export interface DeviceUpdate {
  name?: string
  type?: DeviceType
  ip?: string
  zone?: string
  parent_id?: string | null
  ping_port?: number
  notes?: string
}

export interface HistorySampleOut {
  latency_ms: number | null
  timestamp: string
}

/** GET /api/flaps row: session-cumulative status-flap count per device. */
export interface FlapCountOut {
  device_id: string
  flap_count: number
}
