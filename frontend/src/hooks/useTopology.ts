import { usePolled } from '@/hooks/usePolled'
import { fetchLinks, fetchSpof } from '@/lib/api'

// Links and the analysis only change when an admin edits the topology, so a
// slow refresh is enough to pick that up.
const TOPOLOGY_POLL_MS = 60_000

/** The extra links between devices. */
export function useLinks() {
  return usePolled(fetchLinks, 'links', TOPOLOGY_POLL_MS)
}

/** Single points of failure, largest blast radius first. */
export function useSpof() {
  return usePolled(fetchSpof, 'spof', TOPOLOGY_POLL_MS)
}
