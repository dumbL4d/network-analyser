/** GET /api/health: the API answers, and how the monitoring behind it is doing. */
export interface HealthOut {
  status: string
  app: string
  env: string
  /** When the last poll cycle completed; null until the first one has. */
  last_poll_at: string | null
  last_poll_age_seconds: number | null
  /** No poll cycle has completed for about three poll intervals. */
  poll_stale: boolean
}
