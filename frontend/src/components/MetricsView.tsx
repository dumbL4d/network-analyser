import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Area, ComposedChart, Line, ResponsiveContainer } from 'recharts'

import TimeRangeSelect from '@/components/TimeRangeSelect'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAllDeviceHistories } from '@/hooks/useAllDeviceHistories'
import { useDevices } from '@/hooks/useDevices'
import { useStatusStream } from '@/hooks/useStatusStream'
import { describeResolution, toChartData } from '@/lib/history'
import { computeMedianLatency, computeReachabilityRatio } from '@/lib/metrics'
import { getStatusColor } from '@/lib/statusStyles'
import { cn } from '@/lib/utils'
import type { DeviceStatus, HistoryPoint, HistoryRange } from '@/types/device'

/**
 * Minimal trend sparkline: a bare Recharts chart with no axes or labels,
 * sized to fit an inline table row (~100px wide). For bucketed history it
 * draws the average as the line over a shaded min–max band.
 */
function Sparkline({
  history,
  bucketed,
}: {
  history: HistoryPoint[]
  bucketed: boolean
}) {
  const data = toChartData(history)
  // Red line while the latest point got no reply; otherwise blue.
  const last = history.length ? history[history.length - 1].latency_ms : null
  const stroke = last === null ? '#ef4444' : '#3b82f6'

  return (
    <div className="h-8 w-24 shrink-0">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data}>
          {bucketed && (
            <Area
              type="monotone"
              dataKey="band"
              stroke="none"
              fill={stroke}
              fillOpacity={0.2}
              isAnimationActive={false}
              connectNulls={false}
            />
          )}
          <Line
            type="monotone"
            dataKey="latency_ms"
            stroke={stroke}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function formatLatency(latencyMs: number | null): string {
  return latencyMs === null ? '—' : `${latencyMs.toFixed(2)} ms`
}

function StatusBadge({ status }: { status: DeviceStatus }) {
  const color = getStatusColor(status)
  return (
    <span
      data-testid="status-badge"
      className={cn(
        'rounded-full px-2.5 py-0.5 text-xs font-medium uppercase text-white',
        color.bg,
      )}
    >
      {status}
    </span>
  )
}

export default function MetricsView() {
  const { devices, loading: devicesLoading, error: devicesError } = useDevices()
  const { statuses } = useStatusStream()
  const [range, setRange] = useState<HistoryRange>('live')
  const {
    historiesByDevice,
    resolution,
    loading: historiesLoading,
    error: historiesError,
  } = useAllDeviceHistories(devices, range)
  const bucketed = resolution !== 'raw'

  if (devicesLoading) {
    return (
      <div className="p-8">
        <h1 className="text-xl font-semibold">Metrics</h1>
        <p className="mt-4 text-sm text-muted-foreground">Loading devices…</p>
      </div>
    )
  }

  if (devicesError) {
    return (
      <div className="p-8">
        <h1 className="text-xl font-semibold">Metrics</h1>
        <p className="mt-4 text-sm text-red-600">
          Failed to load devices: {devicesError}
        </p>
      </div>
    )
  }

  // Latency tab rows: sorted by reachability ASCENDING so the worst-performing
  // devices surface at the top. This page is for spotting problems, so
  // alphabetical order would bury the interesting rows -- a deliberate
  // departure from the Status Overview tab's alphabetical sort.
  const latencyRows = devices
    .map((device) => ({
      device,
      history: historiesByDevice[device.id] ?? [],
      median: computeMedianLatency(historiesByDevice[device.id] ?? []),
      reachability: computeReachabilityRatio(
        historiesByDevice[device.id] ?? [],
      ),
    }))
    .sort(
      (a, b) =>
        a.reachability - b.reachability ||
        a.device.name.localeCompare(b.device.name),
    )

  const hasAnyHistory = Object.keys(historiesByDevice).length > 0

  // Status Overview rows: alphabetical by name. This tab is for quick visual
  // scanning of the whole fleet at a glance, not problem-spotting, so the
  // natural default order applies (deliberately unlike the Latency tab).
  const statusRows = [...devices].sort((a, b) =>
    a.name.localeCompare(b.name),
  )

  return (
    <div className="p-8">
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Metrics</h1>
        <p className="text-sm text-muted-foreground">
          Live latency trends and a fleet-wide status overview.
        </p>
      </div>

      <Tabs defaultValue="status">
        <TabsList>
          <TabsTrigger value="latency" data-testid="latency-tab">Latency</TabsTrigger>
          <TabsTrigger value="status" data-testid="status-tab">Status Overview</TabsTrigger>
        </TabsList>

        <TabsContent value="latency">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <div className="flex items-center gap-3">
                <CardTitle className="text-base">Per-device latency</CardTitle>
                <TimeRangeSelect value={range} onChange={setRange} />
              </div>
              <div className="flex gap-8 text-xs text-muted-foreground">
                <span>Median</span>
                <span>Reachability</span>
              </div>
            </CardHeader>
            <CardContent className="divide-y">
              {historiesError ? (
                <p className="py-4 text-sm text-red-600">
                  Failed to load latency history: {historiesError}
                </p>
              ) : historiesLoading && !hasAnyHistory ? (
                <p className="py-4 text-sm text-muted-foreground">
                  Loading latency history…
                </p>
              ) : !hasAnyHistory ? (
                <p className="py-4 text-sm text-muted-foreground">
                  {range === 'live'
                    ? 'No history yet — waiting for the next poll cycle.'
                    : 'No data in this time range yet.'}
                </p>
              ) : (
                latencyRows.map(({ device, history, median, reachability }) => (
                  <div
                    key={device.id}
                    data-testid="latency-row"
                    className="flex items-center justify-between gap-4 py-2"
                  >
                    <Link
                      to={`/devices/${device.id}`}
                      className="w-44 truncate text-sm font-medium transition-colors hover:text-foreground hover:underline"
                    >
                      {device.name}
                    </Link>
                    <div className="flex items-center gap-6">
                      <Sparkline history={history} bucketed={bucketed} />
                      <span
                        data-testid="median"
                        className="w-20 text-right text-sm tabular-nums"
                      >
                        {median === null ? '—' : `${median.toFixed(2)} ms`}
                      </span>
                      <span
                        data-testid="reachability"
                        className="w-12 text-right text-sm tabular-nums"
                      >
                        {reachability}%
                      </span>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
          {hasAnyHistory && (
            <p
              data-testid="history-resolution"
              className="mt-2 text-xs text-muted-foreground"
            >
              Resolution: {describeResolution(resolution)}
            </p>
          )}
        </TabsContent>

        <TabsContent value="status">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Status Overview</CardTitle>
            </CardHeader>
            <CardContent className="divide-y">
              {statusRows.map((device) => {
                const status: DeviceStatus =
                  statuses[device.id]?.status ?? 'unknown'
                const latency = statuses[device.id]?.latency_ms ?? null
                return (
                  <div
                    key={device.id}
                    data-testid="status-row"
                    className="flex items-center justify-between gap-4 py-2"
                  >
                    <div className="flex w-44 items-center gap-3">
                      <span
                        className={cn(
                          'h-2.5 w-2.5 shrink-0 rounded-full',
                          getStatusColor(status).bg,
                        )}
                      />
                      <Link
                        to={`/devices/${device.id}`}
                        className="truncate text-sm font-medium transition-colors hover:text-foreground hover:underline"
                      >
                        {device.name}
                      </Link>
                    </div>
                    <div className="flex items-center gap-4">
                      <StatusBadge status={status} />
                      <span className="w-20 text-right text-sm tabular-nums text-muted-foreground">
                        {formatLatency(latency)}
                      </span>
                    </div>
                  </div>
                )
              })}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}