import { useEffect, useState } from 'react'

import { fetchDevices } from '@/lib/api'
import type { DeviceOut } from '@/types/device'

/**
 * One-time fetch of the device topology. Devices only change via an admin
 * action, which does not exist yet, so this intentionally does not poll.
 */
export function useDevices() {
  const [devices, setDevices] = useState<DeviceOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    fetchDevices()
      .then((data) => {
        if (!cancelled) setDevices(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  return { devices, loading, error }
}
