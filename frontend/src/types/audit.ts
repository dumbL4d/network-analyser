/** Mirrors the backend audit schemas (GET /api/audit). */
export interface AuditEvent {
  id: number
  ts: string
  /** The username that acted. For a failed login: the name that was tried. */
  actor: string
  /** "<area>.<verb>", e.g. "auth.login_failed" or "device.deleted". */
  action: string
  target: string | null
  ip: string | null
  details: Record<string, unknown>
}

/** One page of audit events, newest first. */
export interface AuditPage {
  total: number
  limit: number
  offset: number
  items: AuditEvent[]
}
