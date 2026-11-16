import { useEffect, useState } from 'react'

import { getStoredToken, subscribeToStatusStream } from '@/lib/api'
import type { DeviceStatusDTO } from '@/types/device'

/**
 * Live device statuses from the backend SSE stream. Usable by any number of
 * components; each mount opens its own EventSource.
 *
 * Every connection is opened with a single-use ticket, and a connection that
 * drops is replaced by a new one with a new ticket: see
 * `subscribeToStatusStream`.
 */
export function useStatusStream() {
  const [statuses, setStatuses] = useState<Record<string, DeviceStatusDTO>>({})
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  useEffect(() => {
    // Guard: this hook is meant to run inside authenticated views (enforced by
    // routing), but without a stored token there is nothing to get a stream
    // ticket with, so do not attempt to open one.
    if (getStoredToken() === null) {
      return
    }

    return subscribeToStatusStream(
      (data) => {
        setStatuses(data)
        setLastUpdate(new Date())
      },
      (err) => {
        console.error('Status stream error', err)
      },
    )
  }, [])

  return { statuses, lastUpdate }
}
