import { Link } from 'react-router-dom'
import { CalendarRange } from 'lucide-react'
import { useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAvailability } from '@/hooks/useAvailability'
import { formatDuration } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DeviceOut } from '@/types/device'
import type { AvailabilityWindow } from '@/types/incident'

const WINDOWS: { value: AvailabilityWindow; label: string; seconds: number }[] = [
  { value: '24h', label: 'Last 24 hours', seconds: 24 * 3600 },
  { value: '7d', label: 'Last 7 days', seconds: 7 * 24 * 3600 },
  { value: '30d', label: 'Last 30 days', seconds: 30 * 24 * 3600 },
]

function uptimeTone(percent: number | null) {
  if (percent === null) return 'text-slate-400'
  if (percent >= 99.9) return 'text-emerald-700'
  if (percent >= 99) return 'text-amber-700'
  return 'text-rose-700'
}

function uptimeBar(percent: number | null) {
  if (percent === null) return 'bg-slate-300'
  if (percent >= 99.9) return 'bg-emerald-500'
  if (percent >= 99) return 'bg-amber-500'
  return 'bg-rose-500'
}

/**
 * Per-device uptime over a selectable window, lowest first. Uptime is the
 * share of the monitored time a device was not "down" (degraded counts as up).
 */
export default function AvailabilityTable({ devices }: { devices: DeviceOut[] }) {
  const [window, setWindow] = useState<AvailabilityWindow>('24h')
  const { data, loading, error } = useAvailability(window)

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId
  const windowSeconds =
    WINDOWS.find((option) => option.value === window)?.seconds ?? 0
  const rows = data?.devices ?? []
  const averageUptime =
    rows.length === 0
      ? null
      : rows.reduce((sum, row) => sum + (row.uptime_percent ?? 0), 0) /
        rows.length
  const totalOutages = rows.reduce((sum, row) => sum + row.outages, 0)

  return (
    <Card data-testid="availability" className="overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 border-b border-slate-100 pb-4">
        <div>
          <CardTitle>Availability</CardTitle>
          <p className="mt-1 text-[11px] text-slate-500">
            Share of monitored time each device was not down. Lowest first.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-4 border-r border-slate-200 pr-4 sm:flex">
            <div className="text-right">
              <p className="text-[9px] uppercase tracking-[0.1em] text-slate-400">
                Fleet avg
              </p>
              <p
                className={cn(
                  'mono mt-0.5 text-[12px] font-semibold',
                  uptimeTone(averageUptime),
                )}
              >
                {averageUptime === null ? '—' : `${averageUptime.toFixed(2)}%`}
              </p>
            </div>
            <div className="text-right">
              <p className="text-[9px] uppercase tracking-[0.1em] text-slate-400">
                Outages
              </p>
              <p className="mono mt-0.5 text-[12px] font-semibold text-slate-700">
                {totalOutages}
              </p>
            </div>
          </div>
          <Select
            value={window}
            onValueChange={(next) => setWindow(next as AvailabilityWindow)}
          >
            <SelectTrigger
              data-testid="availability-window"
              aria-label="Availability window"
              className="h-8 w-[154px] text-[11px]"
            >
              <CalendarRange className="mr-1 h-3.5 w-3.5 text-slate-400" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {error !== null && rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-[12px] text-rose-600">
            Failed to load availability: {error}
          </p>
        ) : loading && rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-[12px] text-slate-500">
            Loading availability…
          </p>
        ) : rows.length === 0 ? (
          <p className="px-5 py-8 text-center text-[12px] text-slate-500">
            No availability data in this window.
          </p>
        ) : (
          <Table className="table-density">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[38%]">Device</TableHead>
                <TableHead>Uptime</TableHead>
                <TableHead className="text-right">Downtime</TableHead>
                <TableHead className="text-right">Outages</TableHead>
                <TableHead className="text-right">Observed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const percent = row.uptime_percent
                return (
                  <TableRow key={row.device_id} data-testid="availability-row">
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/devices/${row.device_id}`}
                          className="text-[12px] font-semibold text-slate-800 transition-colors hover:text-blue-600 hover:underline"
                        >
                          {nameOf(row.device_id)}
                        </Link>
                        {/* Say so when the figure covers less than the window. */}
                        {row.uptime_percent !== null &&
                          row.observed_seconds < windowSeconds * 0.99 && (
                            <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-400">
                              partial window
                            </span>
                          )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={cn('h-full rounded-full', uptimeBar(percent))}
                            style={{ width: `${Math.max(2, percent ?? 0)}%` }}
                          />
                        </div>
                        <span
                          className={cn(
                            'mono w-16 text-right text-[12px] font-semibold',
                            uptimeTone(percent),
                          )}
                        >
                          {percent === null ? '—' : `${percent.toFixed(2)}%`}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="mono text-right text-[12px] text-slate-600">
                      {row.downtime_seconds === 0
                        ? '—'
                        : formatDuration(row.downtime_seconds)}
                    </TableCell>
                    <TableCell className="text-right">
                      <span
                        className={cn(
                          'mono inline-flex min-w-6 justify-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold',
                          row.outages > 0
                            ? 'bg-rose-50 text-rose-700'
                            : 'bg-emerald-50 text-emerald-700',
                        )}
                      >
                        {row.outages}
                      </span>
                    </TableCell>
                    <TableCell className="mono text-right text-[11px] text-slate-400">
                      {formatDuration(row.observed_seconds)}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
