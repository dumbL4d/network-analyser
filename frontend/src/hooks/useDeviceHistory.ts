import { useEffect, useState } from 'react'

import { loadHistory, refreshMs } from '@/lib/history'
import type { HistoryPoint, HistoryRange } from '@/types/device'

interface HistoryState {
  key: string
  history: HistoryPoint[]
  resolution: string
  loading: boolean
  error: string | null
}

/**
 * Latency history of one device for a time range. Fetches on mount and
 * whenever the device or the range changes, then re-fetches while the view
 * stays mounted: every 10s for 'live' (history is pull-only; it does not
 * arrive over the SSE stream), every minute for the longer ranges.
 *
 * Known simplification: the 10s is fixed. It does not follow the backend's
 * poll interval (8 s by default), so a new sample shows up to 10 s late.
 */
export function useDeviceHistory(deviceId: string, range: HistoryRange = 'live') {
  const key = `${deviceId}\u0000${range}`
  const [state, setState] = useState<HistoryState>({
    key,
    history: [],
    resolution: 'raw',
    loading: true,
    error: null,
  })

  useEffect(() => {
    let cancelled = false

    const load = () => {
      loadHistory(deviceId, range)
        .then(({ points, resolution }) => {
          if (!cancelled) {
            setState({
              key,
              history: points,
              resolution,
              loading: false,
              error: null,
            })
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setState({
              key,
              history: [],
              resolution: 'raw',
              loading: false,
              error: err instanceof Error ? err.message : String(err),
            })
          }
        })
    }

    load()
    const interval = setInterval(load, refreshMs(range))

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [deviceId, range, key])

  // While the stored state belongs to another device or range, report loading
  // rather than showing the previous selection's points.
  if (state.key !== key) {
    return { history: [], resolution: 'raw', loading: true, error: null }
  }

  return {
    history: state.history,
    resolution: state.resolution,
    loading: state.loading,
    error: state.error,
  }
}
