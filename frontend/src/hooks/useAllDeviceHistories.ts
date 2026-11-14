import { useEffect, useMemo, useState } from 'react'

import { loadHistory, refreshMs } from '@/lib/history'
import type { DeviceOut, HistoryPoint, HistoryRange } from '@/types/device'

interface HistoriesState {
  key: string
  historiesByDevice: Record<string, HistoryPoint[]>
  resolution: string
  loading: boolean
  error: string | null
}

/**
 * Latency history for EVERY device over a time range, fetched concurrently on
 * mount and re-fetched while mounted: every 10s for 'live' (history is
 * pull-only; it never arrives over the SSE stream), every minute for the
 * longer ranges. Returns one `Record<device_id, points>` so the Metrics view
 * can render per-device sparklines without firing requests per render.
 */
export function useAllDeviceHistories(
  devices: DeviceOut[],
  range: HistoryRange = 'live',
) {
  // Memoized so the array identity only changes when `devices` changes, even
  // though it is re-derived by `.map` on every render.
  const deviceIds = useMemo(() => devices.map((device) => device.id), [devices])
  const key = `${deviceIds.join('\u0000')}\u0001${range}`
  const hasDevices = deviceIds.length > 0

  const [state, setState] = useState<HistoriesState>({
    key,
    historiesByDevice: {},
    resolution: 'raw',
    loading: true,
    error: null,
  })

  useEffect(() => {
    if (!hasDevices) return

    let cancelled = false

    const load = () => {
      Promise.all(
        deviceIds.map((deviceId) =>
          loadHistory(deviceId, range).then((history) => ({
            deviceId,
            history,
          })),
        ),
      )
        .then((results) => {
          if (cancelled) return
          const historiesByDevice: Record<string, HistoryPoint[]> = {}
          for (const result of results) {
            historiesByDevice[result.deviceId] = result.history.points
          }
          setState({
            key,
            historiesByDevice,
            // Every device gets the same resolution for the same range.
            resolution: results[0]?.history.resolution ?? 'raw',
            loading: false,
            error: null,
          })
        })
        .catch((err: unknown) => {
          if (cancelled) return
          setState({
            key,
            historiesByDevice: {},
            resolution: 'raw',
            loading: false,
            error: err instanceof Error ? err.message : String(err),
          })
        })
    }

    load()
    const interval = setInterval(load, refreshMs(range))

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [deviceIds, hasDevices, range, key])

  if (!hasDevices) {
    // Nothing to fetch yet (devices still loading) -- stay in a neutral,
    // non-spinning state; the caller tracks the device fetch separately.
    return { historiesByDevice: {}, resolution: 'raw', loading: false, error: null }
  }

  // While the stored state belongs to another device set or range, report
  // loading rather than showing the previous selection's points.
  if (state.key !== key) {
    return { historiesByDevice: {}, resolution: 'raw', loading: true, error: null }
  }

  return {
    historiesByDevice: state.historiesByDevice,
    resolution: state.resolution,
    loading: state.loading,
    error: state.error,
  }
}
