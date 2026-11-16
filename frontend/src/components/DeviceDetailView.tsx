import {
  ArrowLeft,
  ArrowRight,
  Gauge,
  Network,
  Sparkles,
  Timer,
  TrendingDown,
} from 'lucide-react'
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
import DeviceTypeIcon from '@/components/ui/device-type-icon'
import KpiCard from '@/components/ui/kpi-card'
import PageHeader from '@/components/ui/page-header'
import { statusToneClasses } from '@/components/ui/status-badge'
import { Card } from '@/components/ui/card'
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
      className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 transition-colors hover:text-slate-900"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to Topology
    </Link>
  )
}

function InfoRow({
  label,
  children,
  mono,
}: {
  label: string
  children: ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 text-[12px]">
      <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.1em] text-slate-400">
        {label}
      </span>
      <span
        className={cn(
          'text-right font-medium text-slate-700',
          mono && 'mono text-[11px]',
        )}
      >
        {children}
      </span>
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
  const stroke = lastPoint?.latency_ms === null ? '#f43f5e' : '#3b82f6'

  return (
    <div className="h-[320px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={chartData}
          margin={{ top: 12, right: 16, bottom: 8, left: 0 }}
        >
          <CartesianGrid stroke="#f1f5f9" strokeDasharray="4 4" vertical={false} />
          <XAxis
            dataKey="index"
            tick={{ fontSize: 10, fill: '#94a3b8' }}
            axisLine={false}
            tickLine={false}
            minTickGap={40}
            tickFormatter={(index: number) =>
              chartData[index]
                ? formatTick(chartData[index].timestamp, range)
                : ''
            }
          />
          <YAxis
            tick={{ fontSize: 10, fill: '#94a3b8' }}
            axisLine={false}
            tickLine={false}
            width={52}
            unit={spec.unit}
            // Loss is a percentage: always the full scale, so that 5% does
            // not look like a catastrophe.
            domain={metric === 'loss' ? [0, 100] : [0, 'auto']}
          />
          <Tooltip
            cursor={{ stroke: '#cbd5e1', strokeDasharray: '4 4' }}
            contentStyle={{
              border: '1px solid #e2e8f0',
              borderRadius: 10,
              fontSize: 11,
              boxShadow: '0 8px 24px -12px rgb(15 23 42 / 0.25)',
            }}
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
                fill="#a855f7"
                fillOpacity={0.1}
                stroke="#a855f7"
                strokeOpacity={0.35}
              />
            ) : (
              <ReferenceLine
                key={span.id}
                x={span.from}
                xAxisId={0}
                yAxisId={0}
                stroke="#a855f7"
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
              fillOpacity={0.14}
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
    return (
      <p className="text-[11px] text-slate-500">No downstream devices.</p>
    )
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
              className="group flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-slate-50"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500">
                <DeviceTypeIcon type={child.type} className="h-3 w-3" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[12px] font-medium text-slate-800 group-hover:text-blue-600">
                  {child.name}
                </span>
                <span className="mono block truncate text-[9px] text-slate-400">
                  {child.id}
                </span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className={cn('h-1.5 w-1.5 rounded-full', color.bg)} />
                <span className="text-[10px] capitalize text-slate-500">
                  {childStatus}
                </span>
              </span>
              <ArrowRight className="h-3 w-3 text-slate-300 group-hover:text-blue-500" />
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
  const tone = statusToneClasses(status)

  if (devicesLoading) {
    return (
      <div className="page-shell">
        <BackToTopology />
        <Card className="mt-5 p-10 text-center text-[12px] text-slate-500">
          Loading device…
        </Card>
      </div>
    )
  }

  if (devicesError) {
    return (
      <div className="page-shell">
        <BackToTopology />
        <Card className="mt-5 border-rose-200 p-6 text-[12px] text-rose-700">
          Failed to load devices: {devicesError}
        </Card>
      </div>
    )
  }

  if (!device) {
    return (
      <div className="page-shell">
        <BackToTopology />
        <Card className="mt-5 p-10 text-center">
          <p className="text-[16px] font-semibold text-slate-900">
            Device not found
          </p>
          <p className="mt-1 text-[12px] text-slate-500">
            No device with id “{deviceId}” exists.
          </p>
          <Link
            to="/"
            className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-700 shadow-card transition-colors hover:bg-slate-50"
          >
            <ArrowLeft className="h-3 w-3" />
            Back to Topology
          </Link>
        </Card>
      </div>
    )
  }

  const parent = device.parent_id
    ? devices.find((item) => item.id === device.parent_id)
    : null
  const notes = device.notes.trim() === '' ? 'No notes' : device.notes

  const latency = statuses[deviceId]?.latency_ms ?? null
  const loss = statuses[deviceId]?.loss_pct ?? null
  const jitter = statuses[deviceId]?.jitter_ms ?? null
  const lossOver =
    loss !== null &&
    settings !== null &&
    loss >= settings.loss_warn_pct
  const jitterOver =
    jitter !== null &&
    settings !== null &&
    jitter >= settings.jitter_warn_ms

  return (
    <div className="page-shell">
      <BackToTopology />

      <div className="mt-3">
        <PageHeader
          eyebrow={
            <span className="label-caps flex items-center gap-1.5">
              <DeviceTypeIcon type={device.type} className="h-3 w-3" />
              {device.type}
              <span className="h-1 w-1 rounded-full bg-slate-300" />
              {device.zone}
            </span>
          }
          title={device.name}
          description={`${device.id} · ${device.ip} · ping port ${device.ping_port}`}
          actions={
            <span
              data-testid="device-status-badge"
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em]',
                tone.badge,
              )}
            >
              <span className={cn('h-1.5 w-1.5 rounded-full', tone.dot)} />
              {status}
            </span>
          }
        />
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard
          label="Current latency"
          value={formatReading(latency, 'ms')}
          hint="Average round-trip of the latest probe cycle"
          icon={Gauge}
          tone="blue"
        />
        <KpiCard
          label="Packet loss"
          value={
            <span data-testid="current-loss">
              {formatReading(loss, '%', 0)}
            </span>
          }
          hint={
            settings ? `Degraded at ${settings.loss_warn_pct}% or above` : 'Latest probe cycle'
          }
          icon={TrendingDown}
          tone={lossOver ? 'amber' : 'neutral'}
        />
        <KpiCard
          label="Jitter"
          value={
            <span data-testid="current-jitter">
              {formatReading(jitter, 'ms')}
            </span>
          }
          hint={
            settings
              ? `Degraded at ${settings.jitter_warn_ms} ms or above`
              : 'Mean change between round-trips'
          }
          icon={Timer}
          tone={jitterOver ? 'amber' : 'neutral'}
        />
        <KpiCard
          label="Anomaly (advisory)"
          value={
            <span data-testid="current-anomaly" className="text-[13px] leading-snug">
              {anomaly ? describeAnomaly(anomaly) : 'None'}
            </span>
          }
          hint="Never changes status or opens an incident"
          icon={Sparkles}
          tone={anomaly ? 'violet' : 'neutral'}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <p className="text-[13px] font-semibold text-slate-900">
                  Device
                </p>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  Inventory and topology position
                </p>
              </div>
              <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
                <Network className="h-4 w-4" />
              </span>
            </div>
            <div className="divide-y divide-slate-100 px-5 py-1">
              <InfoRow label="Type">
                <span className="capitalize">{device.type}</span>
              </InfoRow>
              <InfoRow label="Zone">{device.zone}</InfoRow>
              <InfoRow label="IP" mono>
                {device.ip}
              </InfoRow>
              <InfoRow label="Ping port" mono>
                {device.ping_port}
              </InfoRow>
              <InfoRow label="Parent">
                {device.parent_id ? (
                  <Link
                    to={`/devices/${device.parent_id}`}
                    className="font-medium text-blue-600 hover:underline"
                  >
                    {parent?.name ?? device.parent_id}
                  </Link>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </InfoRow>
              <InfoRow label="Notes">
                <span className="font-normal text-slate-500">{notes}</span>
              </InfoRow>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="border-b border-slate-100 px-5 py-4">
              <p className="text-[13px] font-semibold text-slate-900">
                Downstream devices
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Devices that depend on this one
              </p>
            </div>
            <div className="p-3">
              <DownstreamList
                deviceId={deviceId}
                devices={devices}
                statuses={statuses}
              />
            </div>
          </Card>
        </div>

        <Card className="overflow-hidden">
          <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[13px] font-semibold text-slate-900">
                {METRICS[metric].label} history
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Thresholds and anomaly markers are advisory overlays.
              </p>
            </div>
            <TimeRangeSelect value={range} onChange={setRange} />
          </div>

          <div className="px-5 pt-4">
            <Tabs
              value={metric}
              onValueChange={(next) => setMetric(next as HistoryMetric)}
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
          </div>

          <div className="p-5">
            {historyError ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50/60 px-4 py-8 text-center text-[12px] text-rose-700">
                Failed to load history: {historyError}
              </div>
            ) : historyLoading && history.length === 0 ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-16 text-center text-[12px] text-slate-500">
                Loading history…
              </div>
            ) : history.length === 0 ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-16 text-center text-[12px] text-slate-500">
                {range === 'live'
                  ? 'No history yet — waiting for the next poll cycle.'
                  : 'No data in this time range yet.'}
              </div>
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
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
                  <p
                    data-testid="history-resolution"
                    className="text-[10px] text-slate-400"
                  >
                    Resolution: {describeResolution(resolution, metric)} ·{' '}
                    {history.length} points
                  </p>
                  {chartAnomalies.length > 0 && (
                    <p
                      data-testid="anomaly-legend"
                      className="flex items-center gap-1.5 text-[10px] text-violet-600"
                    >
                      <span className="h-2 w-2 rounded-sm bg-violet-400/40" />
                      Shaded: anomaly detector (advisory only)
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
