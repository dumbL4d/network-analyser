import type { DeviceOut } from './device'

export type IncidentCategory = 'root_cause' | 'collateral'

/** A single unhealthy device, classified against the device tree. */
export interface IncidentOut {
  device: DeviceOut
  status: string
  latency_ms: number | null
  category: IncidentCategory
  /** Only set on root causes: the concrete descendants currently affected. */
  downstream_affected: DeviceOut[]
}

// --- stored incidents (the backend's incident tracker) -----------------------

export type IncidentState = 'open' | 'acknowledged' | 'resolved'

export type IncidentEventType =
  | 'opened'
  | 'affected_changed'
  | 'acknowledged'
  | 'note'
  | 'resolved'

/** A stored incident: one outage, keyed by its root-cause device. */
export interface IncidentRecord {
  id: number
  root_device_id: string
  state: IncidentState
  /** The poll at which the root cause was confirmed. */
  opened_at: string
  /** The first failing probe of the streak that led to it. */
  first_failure_at: string
  acknowledged_at: string | null
  acknowledged_by: string | null
  resolved_at: string | null
  /** The most downstream devices affected at the same time. */
  peak_affected_count: number
  affected_device_ids: string[]
}

/** One entry of an incident's timeline. */
export interface IncidentEvent {
  id: number
  ts: string
  type: IncidentEventType
  details: Record<string, unknown>
}

/** GET /api/incidents/{id}: the incident with its timeline, oldest first. */
export interface IncidentDetail extends IncidentRecord {
  events: IncidentEvent[]
}

/** GET /api/incidents/history: one page, most recently opened first. */
export interface IncidentHistoryPage {
  total: number
  limit: number
  offset: number
  items: IncidentRecord[]
}

/** GET /api/stats/incidents. */
export interface IncidentStats {
  count: number
  open_count: number
  resolved_count: number
  /** Mean of (opened - first failing probe), in seconds. */
  mean_detection_delay_seconds: number | null
  /** Mean of (resolved - opened) over resolved incidents, in seconds. */
  mttr_seconds: number | null
  /** Collateral devices that did not get an incident of their own. */
  alerts_suppressed: number
}

export const AVAILABILITY_WINDOWS = ['24h', '7d', '30d'] as const
export type AvailabilityWindow = (typeof AVAILABILITY_WINDOWS)[number]

export interface DeviceAvailability {
  device_id: string
  /** Share of the observed time the device was not down; null if unmonitored. */
  uptime_percent: number | null
  downtime_seconds: number
  outages: number
  /** How much of the window the device was actually monitored for. */
  observed_seconds: number
}

/** GET /api/stats/availability?window=...; lowest uptime first. */
export interface AvailabilityOut {
  window: AvailabilityWindow
  from_time: string
  to_time: string
  devices: DeviceAvailability[]
}

/** Guided-fix steps for one device type + state combination. */
export interface PlaybookOut {
  device_type: string
  state: string
  steps: string[]
}