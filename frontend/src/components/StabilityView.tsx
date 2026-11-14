import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useDevices } from '@/hooks/useDevices'
import { useFlapCounts } from '@/hooks/useFlapCounts'
import { fetchSettings } from '@/lib/api'
import type { AppSettingsOut } from '@/types/settings'

const ABOVE_THRESHOLD_FILL = '#f59e0b'
const BELOW_THRESHOLD_FILL = '#3b82f6'
const DEFAULT_THRESHOLD = 3

// A flap is a confirmed status change. The backend stores every change and
// counts the ones inside its retention window (30 days unless configured
// otherwise), so the counts survive a backend restart.

export default function StabilityView() {
  const { flapCounts, loading, error } = useFlapCounts()
  const { devices, loading: devicesLoading, error: devicesError } = useDevices()
  const [settings, setSettings] = useState<AppSettingsOut | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchSettings()
      .then((data) => {
        if (!cancelled) setSettings(data)
      })
      .catch(() => {
        // Non-fatal: fall back to DEFAULT_THRESHOLD for highlighting only.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const threshold = settings?.flap_threshold ?? DEFAULT_THRESHOLD

  const nameById = new Map(devices.map((device) => [device.id, device.name]))

  // Backend already sorts descending; re-sort defensively so the ranking
  // never silently regresses to a different order client-side.
  const rows = flapCounts
    .map((row) => ({
      id: row.device_id,
      name: nameById.get(row.device_id) ?? row.device_id,
      flapCount: row.flap_count,
    }))
    .sort((a, b) => b.flapCount - a.flapCount || a.name.localeCompare(b.name))

  const allStable = rows.length > 0 && rows.every((row) => row.flapCount === 0)

  if (loading || devicesLoading) {
    return (
      <div className="p-8">
        <h1 className="text-xl font-semibold">Stability</h1>
        <p className="mt-4 text-sm text-muted-foreground">Loading flap counts…</p>
      </div>
    )
  }

  if (error || devicesError) {
    return (
      <div className="p-8">
        <h1 className="text-xl font-semibold">Stability</h1>
        <p className="mt-4 text-sm text-red-600">
          Failed to load flap counts: {error ?? devicesError}
        </p>
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Stability</h1>
        <p className="text-sm text-muted-foreground">
          Devices ranked by confirmed status changes over the retained history
          (the last 30 days by default).
        </p>
      </div>

      {allStable ? (
        <Card data-testid="stability-empty">
          <CardContent className="p-8 text-center">
            <p className="text-sm text-muted-foreground">
              No flapping events in the retained history — all devices stable
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card data-testid="stability-chart">
          <CardHeader>
            <CardTitle className="text-base">Flap count ranking</CardTitle>
            <p className="text-xs text-muted-foreground">
              Flap threshold: {threshold} — devices at or above are highlighted
            </p>
          </CardHeader>
          <CardContent>
            <div className="h-[400px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={rows}
                  layout="vertical"
                  margin={{ top: 0, right: 24, bottom: 0, left: 24 }}
                >
                  <XAxis
                    type="number"
                    allowDecimals={false}
                    tick={{ fontSize: 11 }}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 11 }}
                    width={150}
                  />
                  <Bar dataKey="flapCount" radius={[0, 4, 4, 0]}>
                    {rows.map((row) => (
                      <Cell
                        key={row.id}
                        fill={
                          row.flapCount >= threshold
                            ? ABOVE_THRESHOLD_FILL
                            : BELOW_THRESHOLD_FILL
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">
              Repeated flaps → check cable wear, SFP, or intermittent power.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}