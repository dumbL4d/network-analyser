import { useEffect, useState } from 'react'

import { subscribeToStatusStream } from '@/lib/api'
import type { DeviceStatusDTO } from '@/types/device'

/**
 * Live device statuses from the backend SSE stream. Usable by any number of
 * components; each mount opens its own EventSource.
 */
export function useStatusStream() {
  const [statuses, setStatuses] = useState<Record<string, DeviceStatusDTO>>({})
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  useEffect(() => {
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
