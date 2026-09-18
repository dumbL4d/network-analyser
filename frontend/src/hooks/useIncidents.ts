import { useEffect, useState } from 'react'

import { fetchIncidents, getStoredToken } from '@/lib/api'
import type { IncidentOut } from '@/types/incident'

const INCIDENT_POLL_MS = 10_000

// Single shared hook for the header alert badge and the /incidents view. Reads
// the auth token inside the effect so a login that happens while the hook is
// already mounted (the header renders on every page including /login) kicks
// off the first fetch, and a logout stops further polling.
export function useIncidents() {
  const [incidents, setIncidents] = useState<IncidentOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const hasToken = getStoredToken() !== null

  useEffect(() => {
    if (!hasToken) return

    let cancelled = false

    const load = () => {
      fetchIncidents()
        .then((data) => {
          if (!cancelled) setIncidents(data)
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
    const interval = setInterval(load, INCIDENT_POLL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [hasToken])

  return { incidents, loading, error }
}