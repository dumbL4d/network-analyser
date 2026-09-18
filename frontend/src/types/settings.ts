/** Mirrors the backend's single-row AppSettings singleton (Ticket 4.1). */
export interface AppSettingsOut {
  site_name: string
  poll_interval_seconds: number
  latency_warn_ms: number
  latency_crit_ms: number
  flap_threshold: number
}

/** PATCH /api/settings body (backend SettingsUpdate); all fields optional. */
export interface SettingsUpdate {
  site_name?: string
  poll_interval_seconds?: number
  latency_warn_ms?: number
  latency_crit_ms?: number
  flap_threshold?: number
}