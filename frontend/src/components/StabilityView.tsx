import {
  Activity,
  CircleCheck,
  Gauge,
  Repeat2,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import AvailabilityTable from '@/components/stability/AvailabilityTable'
import KpiCard from '@/components/ui/kpi-card'
import PageHeader from '@/components/ui/page-header'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useDevices } from '@/hooks/useDevices'
import { useFlapCounts } from '@/hooks/useFlapCounts'
import { fetchSettings } from '@/lib/api'
import type { AppSettingsOut } from '@/types/settings'
import { useEffect, useState } from 'react'

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
  const flappingCount = rows.filter((row) => row.flapCount > 0).length
  const totalFlaps = rows.reduce((sum, row) => sum + row.flapCount, 0)
  const aboveThreshold = rows.filter((row) => row.flapCount >= threshold).length

  if (loading || devicesLoading) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow={
            <span className="label-caps flex items-center gap-1.5">
              <Gauge className="h-3 w-3" /> Reliability
            </span>
          }
          title="Stability"
          description="Flap frequency and device availability over retained history."
        />
        <Card className="p-10 text-center text-[12px] text-slate-500">
          Loading stability data…
        </Card>
      </div>
    )
  }

  if (error || devicesError) {
    return (
      <div className="page-shell">
        <PageHeader title="Stability" />
        <Card className="border-rose-200 p-6 text-[12px] text-rose-700">
          Failed to load flap counts: {error ?? devicesError}
        </Card>
      </div>
    )
  }

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow={
          <span className="label-caps flex items-center gap-1.5">
            <Gauge className="h-3 w-3" /> Reliability
            <span className="h-1 w-1 rounded-full bg-slate-300" />
            Retained history
          </span>
        }
        title="Stability"
        description="Devices ranked by confirmed status changes over the retained history (the last 30 days by default)."
        actions={
          <span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-medium text-slate-500 shadow-card">
            Flap threshold
            <span className="mono rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-700">
              {threshold}
            </span>
          </span>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard
          label="Stable devices"
          value={`${Math.max(0, devices.length - flappingCount)}/${devices.length}`}
          hint="Zero confirmed status changes"
          icon={ShieldCheck}
          tone="emerald"
        />
        <KpiCard
          label="Flapping devices"
          value={flappingCount}
          hint="Devices with confirmed transitions"
          icon={Repeat2}
          tone={flappingCount > 0 ? 'amber' : 'neutral'}
        />
        <KpiCard
          label="Total flaps"
          value={totalFlaps}
          hint="Across the retained observation window"
          icon={Activity}
          tone={totalFlaps > 0 ? 'blue' : 'neutral'}
        />
        <KpiCard
          label="Above threshold"
          value={aboveThreshold}
          hint={`Devices at or above ${threshold} flaps`}
          icon={TriangleAlert}
          tone={aboveThreshold > 0 ? 'rose' : 'emerald'}
        />
      </div>

      {allStable ? (
        <Card data-testid="stability-empty" className="overflow-hidden">
          <CardContent className="flex flex-col items-center justify-center px-6 py-14 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-600">
              <CircleCheck className="h-6 w-6" />
            </span>
            <p className="mt-4 text-[14px] font-semibold text-slate-900">
              All devices stable
            </p>
            <p className="mt-1 max-w-md text-[12px] leading-relaxed text-slate-500">
              No flapping events in the retained history — every monitored
              device has held a confirmed state.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card data-testid="stability-chart" className="overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-slate-100 pb-4">
            <div>
              <CardTitle>Flap count ranking</CardTitle>
              <p className="mt-1 text-[11px] text-slate-500">
                Devices at or above the threshold are highlighted.
              </p>
            </div>
            <div className="flex items-center gap-3 text-[10px] text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-blue-500" /> Below
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-amber-500" /> At threshold
              </span>
            </div>
          </CardHeader>
          <CardContent className="p-5">
            <div className="h-[340px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={rows}
                  layout="vertical"
                  margin={{ top: 0, right: 24, bottom: 0, left: 10 }}
                >
                  <CartesianGrid
                    stroke="#f1f5f9"
                    strokeDasharray="4 4"
                    horizontal={false}
                  />
                  <XAxis
                    type="number"
                    allowDecimals={false}
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 11, fill: '#475569' }}
                    axisLine={false}
                    tickLine={false}
                    width={155}
                  />
                  <Tooltip
                    cursor={{ fill: '#f8fafc' }}
                    contentStyle={{
                      border: '1px solid #e2e8f0',
                      borderRadius: 10,
                      fontSize: 11,
                      boxShadow: '0 8px 24px -12px rgb(15 23 42 / 0.25)',
                    }}
                    formatter={(value) => [`${value} flaps`, 'Count']}
                  />
                  <Bar dataKey="flapCount" radius={[0, 5, 5, 0]} barSize={14}>
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
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2.5 text-[11px] text-slate-500">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              Repeated flaps are a hardware signal — check cable wear, SFP
              modules, or intermittent power delivery.
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mt-6">
        <AvailabilityTable devices={devices} />
      </div>
    </div>
  )
}
