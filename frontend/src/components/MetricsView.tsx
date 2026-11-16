import {
  Activity,
  CircleAlert,
  Gauge,
  Radio,
  Signal,
  TrendingUp,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Area,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  YAxis,
} from 'recharts'

import TimeRangeSelect from '@/components/TimeRangeSelect'
import DeviceTypeIcon from '@/components/ui/device-type-icon'
import KpiCard from '@/components/ui/kpi-card'
import PageHeader from '@/components/ui/page-header'
import StatusBadge from '@/components/ui/status-badge'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAllDeviceHistories } from '@/hooks/useAllDeviceHistories'
import { useDevices } from '@/hooks/useDevices'
import { usePolled } from '@/hooks/usePolled'
import { useStatusStream } from '@/hooks/useStatusStream'
import { fetchSettings } from '@/lib/api'
import {
  describeResolution,
  toChartData,
  type HistoryMetric,
} from '@/lib/history'
import {
  computeMean,
  computeMedianLatency,
  computePeak,
  computeReachabilityRatio,
} from '@/lib/metrics'
import { cn } from '@/lib/utils'
import type {
  DeviceOut,
  DeviceStatus,
  HistoryPoint,
  HistoryRange,
} from '@/types/device'

/**
 * Minimal trend sparkline: a bare Recharts chart with no axes or labels,
 * sized to fit an inline table row (~120px wide). For bucketed history it
 * draws the average as the line over a shaded band (min–max for latency,
 * average–peak for loss and jitter). With a `threshold` it also draws where
 * "degraded" begins, as a dashed line, and scales so that the line is in view.
 */
function Sparkline({
  history,
  bucketed,
  metric = 'latency',
  threshold,
}: {
  history: HistoryPoint[]
  bucketed: boolean
  metric?: HistoryMetric
  threshold?: number
}) {
  const data = toChartData(history, metric)
  // Red line while the latest point got no reply; otherwise blue.
  const last = history.length ? history[history.length - 1].latency_ms : null
  const stroke = last === null ? '#f43f5e' : '#3b82f6'
  const fillId = `spark-fill-${metric}`

  return (
    <div className="h-9 w-[118px] shrink-0">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data}>
          <defs>
            <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.18} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          {threshold !== undefined && (
            <YAxis hide domain={metric === 'loss' ? [0, 100] : [0, 'auto']} />
          )}
          {threshold !== undefined && (
            <ReferenceLine
              y={threshold}
              yAxisId={0}
              stroke="#f59e0b"
              strokeDasharray="3 3"
              ifOverflow="extendDomain"
            />
          )}
          {bucketed && (
            <Area
              type="monotone"
              dataKey="band"
              stroke="none"
              fill={stroke}
              fillOpacity={0.16}
              isAnimationActive={false}
              connectNulls={false}
            />
          )}
          <Area
            type="monotone"
            dataKey="value"
            stroke="none"
            fill={`url(#${fillId})`}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={stroke}
            strokeWidth={1.8}
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

/** A figure of the Loss & jitter tab; amber once it reaches its threshold. */
function Figure({
  value,
  unit,
  digits,
  threshold,
  testId,
}: {
  value: number | null
  unit: string
  digits: number
  threshold: number | undefined
  testId: string
}) {
  const over = value !== null && threshold !== undefined && value >= threshold
  return (
    <span
      data-testid={testId}
      className={cn(
        'mono inline-block w-[72px] whitespace-nowrap text-right text-[12px]',
        over ? 'font-semibold text-amber-600' : 'text-slate-700',
      )}
    >
      {value === null ? '—' : `${value.toFixed(digits)} ${unit}`}
    </span>
  )
}

function DeviceCell({ device }: { device: DeviceOut }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500">
        <DeviceTypeIcon type={device.type} className="h-3.5 w-3.5" />
      </span>
      <div className="min-w-0">
        <Link
          to={`/devices/${device.id}`}
          className="block truncate text-[12px] font-semibold text-slate-800 transition-colors hover:text-blue-600 hover:underline"
        >
          {device.name}
        </Link>
        <span className="mono mt-0.5 block truncate text-[9px] text-slate-400">
          {device.id} · {device.zone}
        </span>
      </div>
    </div>
  )
}

function TabCardHeader({
  title,
  description,
  range,
  onRangeChange,
}: {
  title: string
  description: string
  range: HistoryRange
  onRangeChange: (range: HistoryRange) => void
}) {
  return (
    <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 border-b border-slate-100 pb-4">
      <div>
        <CardTitle>{title}</CardTitle>
        <p className="mt-1 text-[11px] text-slate-500">{description}</p>
      </div>
      <TimeRangeSelect value={range} onChange={onRangeChange} />
    </CardHeader>
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
  // The thresholds drawn into the Loss & jitter tab.
  const { data: settings } = usePolled(fetchSettings, 'settings', 60_000)

  if (devicesLoading) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow={
            <span className="label-caps flex items-center gap-1.5">
              <Activity className="h-3 w-3" /> Observability
            </span>
          }
          title="Metrics"
          description="Live latency trends and a fleet-wide status overview."
        />
        <Card className="p-10 text-center text-[12px] text-slate-500">
          Loading devices…
        </Card>
      </div>
    )
  }

  if (devicesError) {
    return (
      <div className="page-shell">
        <PageHeader title="Metrics" />
        <Card className="border-rose-200 p-6 text-[12px] text-rose-700">
          Failed to load devices: {devicesError}
        </Card>
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

  // Loss & jitter rows: the worst packet loss first, then the worst jitter.
  // For bucketed history the mean is the mean of the bucket averages.
  const qualityRows = devices
    .map((device) => {
      const history = historiesByDevice[device.id] ?? []
      return {
        device,
        history,
        lossMean: computeMean(history.map((point) => point.loss_pct)),
        lossPeak: computePeak(history.map((point) => point.loss_max_pct)),
        jitterMean: computeMean(history.map((point) => point.jitter_ms)),
        jitterPeak: computePeak(history.map((point) => point.jitter_max_ms)),
      }
    })
    .sort(
      (a, b) =>
        (b.lossMean ?? -1) - (a.lossMean ?? -1) ||
        (b.jitterMean ?? -1) - (a.jitterMean ?? -1) ||
        a.device.name.localeCompare(b.device.name),
    )

  // Status Overview rows: alphabetical by name. This tab is for quick visual
  // scanning of the whole fleet at a glance, not problem-spotting, so the
  // natural default order applies (deliberately unlike the Latency tab).
  const statusRows = [...devices].sort((a, b) =>
    a.name.localeCompare(b.name),
  )

  const liveStatuses = devices.map(
    (device) => statuses[device.id]?.status ?? 'unknown',
  )
  const healthyCount = liveStatuses.filter((status) => status === 'healthy').length
  const issueCount = liveStatuses.filter(
    (status) => status === 'degraded' || status === 'down',
  ).length
  const medianLive = computeMedianLatency(
    devices.map((device) => ({
      latency_ms: statuses[device.id]?.latency_ms ?? null,
    })),
  )
  const meanLoss = computeMean(
    devices.map((device) => statuses[device.id]?.loss_pct ?? null),
  )

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow={
          <span className="label-caps flex items-center gap-1.5">
            <Activity className="h-3 w-3" /> Observability
            <span className="h-1 w-1 rounded-full bg-slate-300" />
            Fleet telemetry
          </span>
        }
        title="Metrics"
        description="Live latency trends, packet quality, and a fleet-wide status overview."
        actions={
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 shadow-card">
            <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-emerald-500" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500">
              Streaming
            </span>
          </div>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard
          label="Fleet health"
          value={`${healthyCount}/${devices.length}`}
          hint={
            issueCount === 0
              ? 'All monitored devices are healthy'
              : `${issueCount} device${issueCount === 1 ? '' : 's'} need attention`
          }
          icon={Signal}
          tone="emerald"
        />
        <KpiCard
          label="Median latency"
          value={medianLive === null ? '—' : `${medianLive.toFixed(1)} ms`}
          hint="Live estimate across reporting devices"
          icon={Gauge}
          tone="blue"
        />
        <KpiCard
          label="Mean packet loss"
          value={meanLoss === null ? '—' : `${meanLoss.toFixed(1)}%`}
          hint="Latest probe cycle, all devices"
          icon={TrendingUp}
          tone={meanLoss !== null && meanLoss > 0 ? 'amber' : 'neutral'}
        />
        <KpiCard
          label="Monitoring"
          value={issueCount === 0 ? 'Nominal' : 'Attention'}
          hint={
            settings
              ? `${settings.poll_interval_seconds}s poll · ${settings.pings_per_cycle} pings/cycle`
              : 'Awaiting monitoring settings'
          }
          icon={Radio}
          tone={issueCount === 0 ? 'emerald' : 'rose'}
        />
      </div>

      <Tabs defaultValue="status">
        <TabsList className="mb-5">
          <TabsTrigger value="latency" data-testid="latency-tab">
            Latency
          </TabsTrigger>
          <TabsTrigger value="quality" data-testid="quality-tab">
            Loss &amp; jitter
          </TabsTrigger>
          <TabsTrigger value="status" data-testid="status-tab">
            Status Overview
          </TabsTrigger>
        </TabsList>

        <TabsContent value="latency">
          <Card className="overflow-hidden">
            <TabCardHeader
              title="Per-device latency"
              description="Worst reachability first. Sparklines show the selected window."
              range={range}
              onRangeChange={setRange}
            />
            <div>
              <Table className="table-density">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[34%]">Device</TableHead>
                    <TableHead>Live trend</TableHead>
                    <TableHead className="text-right">Median</TableHead>
                    <TableHead className="text-right">Reachability</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {historiesError ? (
                    <TableRow>
                      <TableCell colSpan={4} className="py-8 text-center text-rose-600">
                        Failed to load latency history: {historiesError}
                      </TableCell>
                    </TableRow>
                  ) : historiesLoading && !hasAnyHistory ? (
                    <TableRow>
                      <TableCell colSpan={4} className="py-8 text-center text-slate-500">
                        Loading latency history…
                      </TableCell>
                    </TableRow>
                  ) : !hasAnyHistory ? (
                    <TableRow>
                      <TableCell colSpan={4} className="py-8 text-center text-slate-500">
                        {range === 'live'
                          ? 'No history yet — waiting for the next poll cycle.'
                          : 'No data in this time range yet.'}
                      </TableCell>
                    </TableRow>
                  ) : (
                    latencyRows.map(
                      ({ device, history, median, reachability }) => (
                        <TableRow key={device.id} data-testid="latency-row">
                          <TableCell>
                            <DeviceCell device={device} />
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-3">
                              <Sparkline history={history} bucketed={bucketed} />
                              <span className="hidden text-[10px] text-slate-400 xl:inline">
                                {history.length} pts
                              </span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right">
                            <span
                              data-testid="median"
                              className="mono text-[12px] font-medium text-slate-700"
                            >
                              {median === null ? '—' : `${median.toFixed(2)} ms`}
                            </span>
                          </TableCell>
                          <TableCell className="text-right">
                            <span
                              data-testid="reachability"
                              className={cn(
                                'mono inline-flex min-w-12 justify-end rounded-md px-1.5 py-0.5 text-[11px] font-semibold',
                                reachability >= 99
                                  ? 'bg-emerald-50 text-emerald-700'
                                  : reachability >= 90
                                    ? 'bg-amber-50 text-amber-700'
                                    : 'bg-rose-50 text-rose-700',
                              )}
                            >
                              {reachability}%
                            </span>
                          </TableCell>
                        </TableRow>
                      ),
                    )
                  )}
                </TableBody>
              </Table>
            </div>
            {hasAnyHistory && (
              <div className="flex items-center justify-between border-t border-slate-100 px-5 py-2.5">
                <p className="text-[10px] text-slate-400">
                  Resolution: {describeResolution(resolution)}
                </p>
                <p className="text-[10px] text-slate-400">
                  Sorted by reachability · lowest first
                </p>
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="quality">
          <Card className="overflow-hidden">
            <TabCardHeader
              title="Packet loss & jitter"
              description="Amber values are at or above the configured degradation threshold."
              range={range}
              onRangeChange={setRange}
            />
            <Table className="table-density">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[26%]">Device</TableHead>
                  <TableHead>Loss trend</TableHead>
                  <TableHead className="text-right">Mean</TableHead>
                  <TableHead className="text-right">Peak</TableHead>
                  <TableHead>Jitter trend</TableHead>
                  <TableHead className="text-right">Mean</TableHead>
                  <TableHead className="text-right">Peak</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {historiesError ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-rose-600">
                      Failed to load history: {historiesError}
                    </TableCell>
                  </TableRow>
                ) : historiesLoading && !hasAnyHistory ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-slate-500">
                      Loading history…
                    </TableCell>
                  </TableRow>
                ) : !hasAnyHistory ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-slate-500">
                      {range === 'live'
                        ? 'No history yet — waiting for the next poll cycle.'
                        : 'No data in this time range yet.'}
                    </TableCell>
                  </TableRow>
                ) : (
                  qualityRows.map((row) => (
                    <TableRow key={row.device.id} data-testid="quality-row">
                      <TableCell>
                        <DeviceCell device={row.device} />
                      </TableCell>
                      <TableCell>
                        <Sparkline
                          history={row.history}
                          bucketed={bucketed}
                          metric="loss"
                          threshold={settings?.loss_warn_pct}
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Figure
                          value={row.lossMean}
                          unit="%"
                          digits={1}
                          threshold={settings?.loss_warn_pct}
                          testId="loss-mean"
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Figure
                          value={row.lossPeak}
                          unit="%"
                          digits={0}
                          threshold={settings?.loss_warn_pct}
                          testId="loss-peak"
                        />
                      </TableCell>
                      <TableCell>
                        <Sparkline
                          history={row.history}
                          bucketed={bucketed}
                          metric="jitter"
                          threshold={settings?.jitter_warn_ms}
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Figure
                          value={row.jitterMean}
                          unit="ms"
                          digits={2}
                          threshold={settings?.jitter_warn_ms}
                          testId="jitter-mean"
                        />
                      </TableCell>
                      <TableCell className="text-right">
                        <Figure
                          value={row.jitterPeak}
                          unit="ms"
                          digits={2}
                          threshold={settings?.jitter_warn_ms}
                          testId="jitter-peak"
                        />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
            {hasAnyHistory && (
              <div className="border-t border-slate-100 px-5 py-2.5">
                <p className="text-[10px] text-slate-400">
                  Dashed line: where a device counts as degraded
                  {settings
                    ? ` (${settings.loss_warn_pct}% loss, ${settings.jitter_warn_ms} ms jitter)`
                    : ''}
                  . Resolution: {describeResolution(resolution, 'loss')}
                </p>
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="status">
          <Card className="overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-slate-100 pb-4">
              <div>
                <CardTitle>Status Overview</CardTitle>
                <p className="mt-1 text-[11px] text-slate-500">
                  Current confirmed state for every monitored device.
                </p>
              </div>
              <span className="mono rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-500">
                {devices.length} devices
              </span>
            </CardHeader>
            <Table className="table-density">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[34%]">Device</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Latency</TableHead>
                  <TableHead className="text-right">Loss</TableHead>
                  <TableHead className="text-right">Jitter</TableHead>
                  <TableHead className="text-right">Zone</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {statusRows.map((device) => {
                  const status: DeviceStatus =
                    statuses[device.id]?.status ?? 'unknown'
                  const latency = statuses[device.id]?.latency_ms ?? null
                  return (
                    <TableRow key={device.id} data-testid="status-row">
                      <TableCell>
                        <div className="flex items-center gap-2.5">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500">
                            <DeviceTypeIcon
                              type={device.type}
                              className="h-3.5 w-3.5"
                            />
                          </span>
                          <Link
                            to={`/devices/${device.id}`}
                            className="truncate text-[12px] font-semibold text-slate-800 transition-colors hover:text-blue-600 hover:underline"
                          >
                            {device.name}
                          </Link>
                        </div>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={status} testId="status-badge" />
                      </TableCell>
                      <TableCell className="mono text-right text-[12px] text-slate-600">
                        {formatLatency(latency)}
                      </TableCell>
                      <TableCell className="mono text-right text-[12px] text-slate-600">
                        {statuses[device.id]?.loss_pct === null ||
                        statuses[device.id]?.loss_pct === undefined
                          ? '—'
                          : `${statuses[device.id].loss_pct?.toFixed(0)}%`}
                      </TableCell>
                      <TableCell className="mono text-right text-[12px] text-slate-600">
                        {statuses[device.id]?.jitter_ms === null ||
                        statuses[device.id]?.jitter_ms === undefined
                          ? '—'
                          : `${statuses[device.id].jitter_ms?.toFixed(1)} ms`}
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.05em] text-slate-500">
                          {device.zone}
                        </span>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>
      </Tabs>

      <div className="mt-4 flex items-center gap-1.5 text-[10px] text-slate-400">
        <CircleAlert className="h-3 w-3" />
        Metrics are derived from the latest completed probe cycle. Values
        arrive over the live status stream.
      </div>
    </div>
  )
}
