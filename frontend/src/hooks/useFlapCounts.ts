import { useEffect, useState } from 'react'

import { fetchFlapCounts } from '@/lib/api'
import type { FlapCountOut } from '@/types/device'

// Same simplification as useDeviceHistory (Ticket 2.4): the backend poll
// interval is configurable, but this hook hardcodes the default 10s.
const FLAP_POLL_MS = 10_000

/**
 * Session flap counts, fetched on mount and re-polled every 10s so the
 * Stability view tracks new flap events without a manual refresh.
 */
export function useFlapCounts() {
  const [flapCounts, setFlapCounts] = useState<FlapCountOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = () => {
      fetchFlapCounts()
        .then((data) => {
          if (!cancelled) setFlapCounts(data)
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : String(err))
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }

    load()
    const interval = setInterval(load, FLAP_POLL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return { flapCounts, loading, error }
}