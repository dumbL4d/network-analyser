import { useEffect, useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { subscribeToStatusStream, type DeviceStatusDTO } from '@/lib/api'
import { cn } from '@/lib/utils'

const STATUS_STYLES: Record<DeviceStatusDTO['status'], string> = {
  healthy: 'bg-green-100 text-green-800',
  degraded: 'bg-amber-100 text-amber-800',
  down: 'bg-red-100 text-red-800',
  unknown: 'bg-gray-100 text-gray-700',
}

function App() {
  const [statuses, setStatuses] = useState<Record<string, DeviceStatusDTO>>({})
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [now, setNow] = useState<Date>(() => new Date())

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

  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])

  const deviceIds = Object.keys(statuses).sort()
  const secondsAgo = lastUpdate
    ? Math.max(0, Math.round((now.getTime() - lastUpdate.getTime()) / 1000))
    : null

  return (
    <div className="min-h-screen bg-background p-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Network Analyser — Live Status (Dev Smoke Test)
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tracking {deviceIds.length} device{deviceIds.length === 1 ? '' : 's'}
          {' · '}
          {secondsAgo === null
            ? 'Waiting for first update…'
            : `Last update: ${secondsAgo}s ago`}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
        {deviceIds.map((deviceId) => {
          const device = statuses[deviceId]
          return (
            <Card key={deviceId}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <CardTitle className="text-base">{deviceId}</CardTitle>
                <span
                  data-testid={`status-${deviceId}`}
                  className={cn(
                    'rounded-full px-2.5 py-0.5 text-xs font-medium uppercase',
                    STATUS_STYLES[device.status],
                  )}
                >
                  {device.status}
                </span>
              </CardHeader>
              <CardContent className="space-y-1 text-sm">
                <div>
                  <span className="text-muted-foreground">Latency: </span>
                  {device.latency_ms === null
                    ? '—'
                    : `${device.latency_ms.toFixed(2)} ms`}
                </div>
                <div>
                  <span className="text-muted-foreground">Updated: </span>
                  {new Date(device.timestamp).toLocaleTimeString()}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

export default App
