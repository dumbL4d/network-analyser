import { useEffect, useMemo, useState } from 'react'

import { fetchDeviceHistory } from '@/lib/api'
import type { DeviceOut, HistorySampleOut } from '@/types/device'

// Mirrors useDeviceHistory's hardcoded 10s poll (the backend's configured poll
// interval is not exposed to the hook layer).
const HISTORY_POLL_MS = 10_000

interface HistoriesState {
  deviceIds: string
  historiesByDevice: Record<string, HistorySampleOut[]>
  loading: boolean
  error: string | null
}

/**
 * Rolling latency history for EVERY device, fetched concurrently on mount and
 * re-fetched every 10s (history is pull-only; it never arrives over the SSE
 * stream). Returns one `Record<device_id, samples>` so the Metrics view can
 * render per-device sparklines without firing individual requests per render.
 */
export function useAllDeviceHistories(devices: DeviceOut[]) {
  // Memoized so the array identity only changes when `devices` changes, even
  // though it is re-derived by `.map` on every render.
  const deviceIds = useMemo(() => devices.map((device) => device.id), [devices])
  const deviceIdsKey = deviceIds.join('\u0000')
  const hasDevices = deviceIds.length > 0

  const [state, setState] = useState<HistoriesState>({
    deviceIds: deviceIdsKey,
    historiesByDevice: {},
    loading: true,
    error: null,
  })

  useEffect(() => {
    if (!hasDevices) return

    let cancelled = false

    const load = () => {
      Promise.all(
        deviceIds.map((deviceId) =>
          fetchDeviceHistory(deviceId).then((history) => ({
            deviceId,
            history,
          })),
        ),
      )
        .then((results) => {
          if (cancelled) return
          const historiesByDevice: Record<string, HistorySampleOut[]> = {}
          for (const result of results) {
            historiesByDevice[result.deviceId] = result.history
          }
          setState({
            deviceIds: deviceIdsKey,
            historiesByDevice,
            loading: false,
            error: null,
          })
        })
        .catch((err: unknown) => {
          if (cancelled) return
          setState({
            deviceIds: deviceIdsKey,
            historiesByDevice: {},
            loading: false,
            error: err instanceof Error ? err.message : String(err),
          })
        })
    }

    load()
    const interval = setInterval(load, HISTORY_POLL_MS)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [deviceIds, hasDevices, deviceIdsKey])

  if (!hasDevices) {
    // Nothing to fetch yet (devices still loading) -- stay in a neutral,
    // non-spinning state; the caller tracks the device fetch separately.
    return { historiesByDevice: {}, loading: false, error: null }
  }

  // While the stored state belongs to a different device set, report loading
  // rather than showing a previous device set's samples.
  if (state.deviceIds !== deviceIdsKey) {
    return { historiesByDevice: {}, loading: true, error: null }
  }

  return {
    historiesByDevice: state.historiesByDevice,
    loading: state.loading,
    error: state.error,
  }
}