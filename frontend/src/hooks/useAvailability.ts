import { usePolled } from '@/hooks/usePolled'
import { fetchAvailability } from '@/lib/api'
import type { AvailabilityWindow } from '@/types/incident'

/** Per-device uptime over a window, re-fetched every minute. */
export function useAvailability(window: AvailabilityWindow) {
  return usePolled(() => fetchAvailability(window), window, 60_000)
}
