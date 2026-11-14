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

/** Time ranges GET /api/history/{id}?window=... accepts. */
export const HISTORY_WINDOWS = ['1h', '6h', '24h', '7d', '30d'] as const
export type HistoryWindow = (typeof HISTORY_WINDOWS)[number]

/** A chart's time range. 'live' is the recent in-memory samples (no window). */
export type HistoryRange = 'live' | HistoryWindow

/** One point of a history: a raw reading, or a time bucket (min / avg / max). */
export interface HistoryPoint {
  timestamp: string
  /** The reading, or the bucket's average. Null when nothing replied. */
  latency_ms: number | null
  min_ms: number | null
  max_ms: number | null
  /** Polls this point stands for (1 for a raw reading). */
  sample_count: number
  /** How many of those polls got no reply. */
  fail_count: number
}

/** GET /api/history/{id}?window=... response. */
export interface HistoryWindowOut {
  device_id: string
  window: HistoryWindow
  /** 'raw', or the bucket size the backend used: '1m', '5m', '30m', '2h'. */
  resolution: string
  resolution_seconds: number | null
  points: HistoryPoint[]
}

/** GET /api/flaps row: confirmed status changes of a device in the flap window. */
export interface FlapCountOut {
  device_id: string
  flap_count: number
}
