import { usePolled } from '@/hooks/usePolled'
import {
  fetchIncident,
  fetchIncidentHistory,
  fetchIncidentStats,
} from '@/lib/api'
import type { IncidentState } from '@/types/incident'

const INCIDENT_POLL_MS = 10_000
const STATS_POLL_MS = 30_000

/**
 * A page of stored incidents (most recently opened first), re-fetched every
 * 10s. An empty `states` list means every state.
 */
export function useIncidentHistory(
  states: IncidentState[],
  limit: number,
  offset: number,
) {
  return usePolled(
    () => fetchIncidentHistory({ states, limit, offset }),
    `${states.join(',')}|${limit}|${offset}`,
    INCIDENT_POLL_MS,
  )
}

/** One stored incident with its timeline, re-fetched every 10s. */
export function useIncidentDetail(incidentId: number) {
  return usePolled(
    () => fetchIncident(incidentId),
    String(incidentId),
    INCIDENT_POLL_MS,
  )
}

/** Count, mean detection delay, MTTR and alerts suppressed. */
export function useIncidentStats() {
  return usePolled(fetchIncidentStats, 'incident-stats', STATS_POLL_MS)
}
