import { useEffect, useState } from 'react'

import { fetchDeviceHistory } from '@/lib/api'
import type { HistorySampleOut } from '@/types/device'

// Known simplification: the backend poll interval is configurable
// (PING_INTERVAL_SECONDS), but this hook hardcodes the default 10s rather than
// fetching the backend's configured value.
const HISTORY_POLL_MS = 10_000

interface HistoryState {
  deviceId: string
  history: HistorySampleOut[]
  loading: boolean
  error: string | null
}

/**
 * Fetches rolling latency history for a device on mount, whenever the device
 * changes, and then polls every 10s while the detail view stays mounted
 * (history is pull-only; it does not arrive over the SSE stream).
 */
export function useDeviceHistory(deviceId: string) {
  const [state, setState] = useState<HistoryState>({
    deviceId,
    history: [],
    loading: true,
    error: null,
  })

  useEffect(() => {
    let cancelled = false

    const load = () => {
      fetchDeviceHistory(deviceId)
        .then((data) => {
          if (!cancelled) {
            setState({ deviceId, history: data, loading: false, error: null })
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setState({
              deviceId,
              history: [],
              loading: false,
              error: err instanceof Error ? err.message : String(err),
            })
          }
        })
    }

    load()
    const interval = setInterval(load, HISTORY_POLL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [deviceId])

  // While the stored state belongs to a previous deviceId, report loading
  // rather than showing the previous device's samples.
  if (state.deviceId !== deviceId) {
    return { history: [], loading: true, error: null }
  }

  return {
    history: state.history,
    loading: state.loading,
    error: state.error,
  }
}
