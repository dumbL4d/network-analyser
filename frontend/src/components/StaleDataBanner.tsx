import { usePolled } from '@/hooks/usePolled'
import { fetchHealth } from '@/lib/api'
import { formatDuration } from '@/lib/format'

const HEALTH_POLL_MS = 10_000

/**
 * A warning across every page behind the login while the statuses on it may
 * be out of date: the backend reports that no poll cycle has completed for
 * about three poll intervals (GET /api/health decides, not this page), or it
 * does not answer (the request fails, or times out: see `fetchHealth`).
 */
export default function StaleDataBanner() {
  const { data: health, error } = usePolled(fetchHealth, 'health', HEALTH_POLL_MS)

  let reason: string
  let age: string | null = null
  if (error !== null) {
    reason = 'The backend is not answering.'
  } else if (!health?.poll_stale) {
    return null
  } else if (health.last_poll_age_seconds === null) {
    reason = 'Monitoring has not completed a poll yet.'
  } else {
    reason = 'Monitoring has fallen behind.'
    age = formatDuration(health.last_poll_age_seconds)
  }

  return (
    <div
      data-testid="stale-banner"
      // sticky: on a page that is scrolled down it must still be in view.
      className="sticky top-0 z-40 border-b border-amber-300 bg-amber-50 px-6 py-2 text-sm text-amber-900"
    >
      {/* Only the sentence that stays the same is an alert: the age changes
          with every poll, and a screen reader would read it out each time. */}
      <span role="alert">{reason} The statuses shown may be out of date.</span>
      {age !== null && <span> The last poll finished {age} ago.</span>}
    </div>
  )
}
