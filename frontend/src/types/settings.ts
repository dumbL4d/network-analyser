/** Mirrors the backend's single-row AppSettings singleton. */
export interface AppSettingsOut {
  site_name: string
  poll_interval_seconds: number
  latency_warn_ms: number
  latency_crit_ms: number
  flap_threshold: number
  /** Debouncing: bad polls in a row before a worse status is confirmed (1-10). */
  failure_threshold: number
  /** Debouncing: good polls in a row before a better status is confirmed (1-10). */
  recovery_threshold: number
  /** Probing: pings sent to a device per poll cycle (1-10). */
  pings_per_cycle: number
  /** Probing: time from one of those pings to the next, in ms. */
  ping_gap_ms: number
  /** A device is degraded from this much packet loss (percent). */
  loss_warn_pct: number
  /** A device is degraded from this much jitter (ms). */
  jitter_warn_ms: number
  /** Anomaly detection (advisory): on or off, and which detector. */
  anomaly_enabled: boolean
  anomaly_detector: 'ewma' | 'rolling'
  /** A reading counts when it is this many standard deviations above normal ... */
  anomaly_k: number
  /** ... and an anomaly is this many such readings in a row. */
  anomaly_m: number
  /** How fast the EWMA detector forgets (0.01-0.5). */
  anomaly_alpha: number
  /** How many readings the rolling detector looks back on (30-1000). */
  anomaly_window: number
}

/** PATCH /api/settings body (backend SettingsUpdate); all fields optional. */
export interface SettingsUpdate {
  site_name?: string
  poll_interval_seconds?: number
  latency_warn_ms?: number
  latency_crit_ms?: number
  flap_threshold?: number
  failure_threshold?: number
  recovery_threshold?: number
  pings_per_cycle?: number
  ping_gap_ms?: number
  loss_warn_pct?: number
  jitter_warn_ms?: number
  anomaly_enabled?: boolean
  anomaly_detector?: 'ewma' | 'rolling'
  anomaly_k?: number
  anomaly_m?: number
  anomaly_alpha?: number
  anomaly_window?: number
}