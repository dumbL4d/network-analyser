import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import TimeRangeSelect from '@/components/TimeRangeSelect'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDeviceHistory } from '@/hooks/useDeviceHistory'
import { useDevices } from '@/hooks/useDevices'
import { usePolled } from '@/hooks/usePolled'
import { useStatusStream } from '@/hooks/useStatusStream'
import { describeAnomaly } from '@/lib/anomaly'
import { fetchAnomalies, fetchSettings } from '@/lib/api'
import {
  METRICS,
  describeResolution,
  formatTick,
  toChartData,
  type ChartDatum,
  type HistoryMetric,
} from '@/lib/history'
import { getStatusColor } from '@/lib/statusStyles'
import { cn } from '@/lib/utils'
import type {
  AnomalyEvent,
  DeviceOut,
  DeviceStatusDTO,
  HistoryPoint,
  HistoryRange,
} from '@/types/device'

function BackToTopology() {
  return (
    <Link
      to="/"
      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      ← Back to Topology
    </Link>
  )
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  )
}

/** A reading with its unit, or a dash when there is none. */
function formatReading(
  value: number | null | undefined,
  unit: string,
  digits = 2,
): string {
  return value === null || value === undefined
    ? '—'
    : `${value.toFixed(digits)} ${unit}`
}

/**
 * Which points of the chart each anomaly covers: from the point at (or just
 * before) its beginning to the point at (or just before) its end, or the last
 * point while it is still going on. Anomalies outside the chart are left out.
 */
function anomalySpans(
  chartData: ChartDatum[],
  anomalies: AnomalyEvent[],
): { id: number; from: number; to: number }[] {
  const times = chartData.map((datum) => Date.parse(datum.timestamp))
  if (times.length === 0) return []
  // The last point at or before a moment; -1 if the chart begins after it.
  const pointAt = (moment: number) => {
    let point = -1
    while (point + 1 < times.length && times[point + 1] <= moment) point += 1
    return point
  }
  return anomalies.flatMap((anomaly) => {
    const to = pointAt(
      anomaly.ended_at === null ? Infinity : Date.parse(anomaly.ended_at),
    )
    const began = Date.parse(anomaly.started_at)
    if (to === -1 || began > times[times.length - 1]) return []
    return [{ id: anomaly.id, from: Math.max(pointAt(began), 0), to }]
  })
}

function HistoryChart({
  history,
  range,
  bucketed,
  metric,
  threshold,
  anomalies,
}: {
  history: HistoryPoint[]
  range: HistoryRange
  /** True when each point is a time bucket (min / avg / max), not one poll. */
  bucketed: boolean
  metric: HistoryMetric
  /** Where "degraded" begins for this metric; drawn as a dashed line. */
  threshold: number | undefined
  /** What the anomaly detector found for this metric; shaded on the chart. */
  anomalies: AnomalyEvent[]
}) {
  const spec = METRICS[metric]
  const chartData = toChartData(history, metric)
  const spans = anomalySpans(chartData, anomalies)

  // Simple heuristic: red when the most recent point got no reply.
  const lastPoint = history.length ? history[history.length - 1] : null
  const stroke = lastPoint?.latency_ms === null ? '#ef4444' : '#3b82f6'

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={chartData}
          margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          <XAxis
            dataKey="index"
            tick={{ fontSize: 11 }}
            minTickGap={40}
            tickFormatter={(index: number) =>
              chartData[index]
                ? formatTick(chartData[index].timestamp, range)
                : ''
            }
          />
          <YAxis
            tick={{ fontSize: 11 }}
            width={52}
            unit={spec.unit}
            // Loss is a percentage: always the full scale, so that 5% does
            // not look like a catastrophe.
            domain={metric === 'loss' ? [0, 100] : [0, 'auto']}
          />
          <Tooltip
            formatter={(value, name) => {
              if (name === 'band') {
                const [low, high] = value as [number, number]
                return [
                  `${low.toFixed(2)} – ${high.toFixed(2)} ${spec.unit}`,
                  spec.bandLabel,
                ]
              }
              const label = spec.label.toLowerCase()
              return value === null
                ? [metric === 'latency' ? 'down (no latency)' : 'not measured', label]
                : [
                    `${Number(value).toFixed(2)} ${spec.unit}`,
                    bucketed ? 'average' : label,
                  ]
            }}
            labelFormatter={(_label, payload) => {
              const datum = payload?.[0]?.payload as ChartDatum | undefined
              if (!datum) return ''
              const when = new Date(datum.timestamp).toLocaleString()
              return bucketed
                ? `${when} · ${datum.sample_count} polls, ${datum.fail_count} without a reply`
                : when
            }}
          />
          {/* Where "degraded" begins. For latency the line only shows when
              the readings come near it; for loss and jitter the axis makes
              room for it, so the distance to it is always visible. (yAxisId
              is spelled out because, with React 19, Recharts does not see
              the default when it works out how far to extend the axis.) */}
          {threshold !== undefined && (
            <ReferenceLine
              y={threshold}
              yAxisId={0}
              stroke="#f59e0b"
              strokeDasharray="5 4"
              ifOverflow={metric === 'jitter' ? 'extendDomain' : 'discard'}
              label={{
                value: `degraded from ${threshold} ${spec.unit}`,
                // On the left: the newest readings are on the right.
                position: 'insideTopLeft',
                fontSize: 10,
                fill: '#b45309',
              }}
            />
          )}
          {/* Advisory: the periods the anomaly detector found unusual. One
              that fits in a single point is drawn as a line. */}
          {spans.map((span) =>
            span.to > span.from ? (
              <ReferenceArea
                key={span.id}
                x1={span.from}
                x2={span.to}
                xAxisId={0}
                yAxisId={0}
                fill="#c026d3"
                fillOpacity={0.12}
                stroke="#c026d3"
                strokeOpacity={0.45}
              />
            ) : (
              <ReferenceLine
                key={span.id}
                x={span.from}
                xAxisId={0}
                yAxisId={0}
                stroke="#c026d3"
                strokeDasharray="2 2"
              />
            ),
          )}
          {/* The band only means something for buckets. */}
          {bucketed && (
            <Area
              type="monotone"
              dataKey="band"
              stroke="none"
              fill={stroke}
              fillOpacity={0.18}
              isAnimationActive={false}
              connectNulls={false}
            />
          )}
          <Line
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={2}
            dot={chartData.length > 60 ? false : { r: 2 }}
            isAnimationActive={false}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function DownstreamList({
  deviceId,
  devices,
  statuses,
}: {
  deviceId: string
  devices: DeviceOut[]
  statuses: Record<string, DeviceStatusDTO>
}) {
  const children = devices.filter((device) => device.parent_id === deviceId)

  if (children.length === 0) {
    return <p className="text-sm text-muted-foreground">No downstream devices.</p>
  }

  return (
    <ul className="space-y-1">
      {children.map((child) => {
        const childStatus = statuses[child.id]?.status ?? 'unknown'
        const color = getStatusColor(childStatus)
        return (
          <li key={child.id}>
            <Link
              to={`/devices/${child.id}`}
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted"
            >
              <span className={cn('h-2.5 w-2.5 rounded-full', color.bg)} />
              <span className="font-medium">{child.name}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {childStatus}
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

export default function DeviceDetailView() {
  const { deviceId = '' } = useParams<{ deviceId: string }>()
  const { devices, loading: devicesLoading, error: devicesError } = useDevices()
  const { statuses } = useStatusStream()
  const [range, setRange] = useState<HistoryRange>('live')
  const [metric, setMetric] = useState<HistoryMetric>('latency')
  const {
    history,
    resolution,
    loading: historyLoading,
    error: historyError,
  } = useDeviceHistory(deviceId, range)
  // The thresholds for the charts' "degraded from" lines.
  const { data: settings } = usePolled(fetchSettings, 'settings', 60_000)
  // What the anomaly detector found for this device, for the chart markers.
  const { data: anomalyEvents } = usePolled(
    () => fetchAnomalies({ deviceId, limit: 200 }),
    deviceId,
    10_000,
  )
  const chartAnomalies = (anomalyEvents ?? []).filter(
    (event) => event.metric === metric,
  )
  const anomaly = statuses[deviceId]?.anomaly ?? null
  const thresholds: Record<HistoryMetric, number | undefined> = {
    latency: settings?.latency_warn_ms,
    loss: settings?.loss_warn_pct,
    jitter: settings?.jitter_warn_ms,
  }

  const device = devices.find((item) => item.id === deviceId)
  const status = statuses[deviceId]?.status ?? 'unknown'
  const color = getStatusColor(status)

  if (devicesLoading) {
    return (
      <div className="p-8">
        <BackToTopology />
        <p className="mt-6 text-sm text-muted-foreground">Loading device…</p>
      </div>
    )
  }

  if (devicesError) {
    return (
      <div className="p-8">
        <BackToTopology />
        <p className="mt-6 text-sm text-red-600">
          Failed to load devices: {devicesError}
        </p>
      </div>
    )
  }

  if (!device) {
    return (
      <div className="p-8">
        <BackToTopology />
        <div className="mt-6">
          <h1 className="text-xl font-semibold">Device not found</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            No device with id “{deviceId}” exists.
          </p>
          <Link
            to="/"
            className="mt-4 inline-block rounded-md border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted"
          >
            Back to Topology
          </Link>
        </div>
      </div>
    )
  }

  const parent = device.parent_id
    ? devices.find((item) => item.id === device.parent_id)
    : null
  const notes = device.notes.trim() === '' ? 'No notes' : device.notes

  return (
    <div className="p-8">
      <BackToTopology />
      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle>{device.name}</CardTitle>
            <span
              data-testid="device-status-badge"
              className={cn(
                'rounded-full px-2.5 py-0.5 text-xs font-medium uppercase text-white',
                color.bg,
              )}
            >
              {status}
            </span>
          </CardHeader>
          <CardContent className="divide-y">
            <InfoRow label="Type">{device.type}</InfoRow>
            <InfoRow label="Zone">{device.zone}</InfoRow>
            <InfoRow label="IP">{device.ip}</InfoRow>
            <InfoRow label="Ping port">{device.ping_port}</InfoRow>
            <InfoRow label="Current latency">
              {formatReading(statuses[deviceId]?.latency_ms, 'ms')}
            </InfoRow>
            <InfoRow label="Packet loss">
              <span data-testid="current-loss">
                {formatReading(statuses[deviceId]?.loss_pct, '%', 0)}
              </span>
            </InfoRow>
            <InfoRow label="Jitter">
              <span data-testid="current-jitter">
                {formatReading(statuses[deviceId]?.jitter_ms, 'ms')}
              </span>
            </InfoRow>
            <InfoRow label="Anomaly (advisory)">
              <span
                data-testid="current-anomaly"
                className={anomaly ? 'text-fuchsia-700' : 'text-muted-foreground'}
              >
                {anomaly ? describeAnomaly(anomaly) : 'None'}
              </span>
            </InfoRow>
            <InfoRow label="Parent">
              {device.parent_id ? (
                <Link
                  to={`/devices/${device.parent_id}`}
                  className="text-blue-600 hover:underline"
                >
                  {parent?.name ?? device.parent_id}
                </Link>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </InfoRow>
            <InfoRow label="Notes">{notes}</InfoRow>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">
                {METRICS[metric].label} history
              </CardTitle>
              <TimeRangeSelect value={range} onChange={setRange} />
            </CardHeader>
            <CardContent>
              <Tabs
                value={metric}
                onValueChange={(next) => setMetric(next as HistoryMetric)}
                className="mb-3"
              >
                <TabsList>
                  <TabsTrigger value="latency" data-testid="metric-latency">
                    Latency
                  </TabsTrigger>
                  <TabsTrigger value="loss" data-testid="metric-loss">
                    Packet loss
                  </TabsTrigger>
                  <TabsTrigger value="jitter" data-testid="metric-jitter">
                    Jitter
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              {historyError ? (
                <p className="text-sm text-red-600">
                  Failed to load history: {historyError}
                </p>
              ) : historyLoading && history.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Loading history…
                </p>
              ) : history.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {range === 'live'
                    ? 'No history yet — waiting for the next poll cycle.'
                    : 'No data in this time range yet.'}
                </p>
              ) : (
                <div data-testid="latency-sparkline">
                  <HistoryChart
                    history={history}
                    range={range}
                    bucketed={resolution !== 'raw'}
                    metric={metric}
                    threshold={thresholds[metric]}
                    anomalies={chartAnomalies}
                  />
                  <p
                    data-testid="history-resolution"
                    className="mt-2 text-xs text-muted-foreground"
                  >
                    Resolution: {describeResolution(resolution, metric)} ·{' '}
                    {history.length} points
                  </p>
                  {chartAnomalies.length > 0 && (
                    <p
                      data-testid="anomaly-legend"
                      className="mt-1 text-xs text-fuchsia-700"
                    >
                      Shaded: what the anomaly detector found unusual
                      (advisory: the status is not affected).
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Downstream devices</CardTitle>
            </CardHeader>
            <CardContent>
              <DownstreamList
                deviceId={deviceId}
                devices={devices}
                statuses={statuses}
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
