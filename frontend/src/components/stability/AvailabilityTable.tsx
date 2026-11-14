import { useState } from 'react'
import { Link } from 'react-router-dom'

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
import type { DeviceOut } from '@/types/device'
import type { AvailabilityWindow } from '@/types/incident'

const WINDOWS: { value: AvailabilityWindow; label: string; seconds: number }[] = [
  { value: '24h', label: 'Last 24 hours', seconds: 24 * 3600 },
  { value: '7d', label: 'Last 7 days', seconds: 7 * 24 * 3600 },
  { value: '30d', label: 'Last 30 days', seconds: 30 * 24 * 3600 },
]

/**
 * Per-device uptime over a selectable window, lowest first. Uptime is the
 * share of the monitored time a device was not "down" (degraded counts as up).
 */
export default function AvailabilityTable({ devices }: { devices: DeviceOut[] }) {
  const [window, setWindow] = useState<AvailabilityWindow>('24h')
  const { data, loading, error } = useAvailability(window)

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId
  const windowSeconds = WINDOWS.find((option) => option.value === window)?.seconds ?? 0
  const rows = data?.devices ?? []

  return (
    <Card data-testid="availability">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base">Availability</CardTitle>
          <p className="text-xs text-muted-foreground">
            Share of the monitored time each device was not down. Lowest first.
          </p>
        </div>
        <Select
          value={window}
          onValueChange={(next) => setWindow(next as AvailabilityWindow)}
        >
          <SelectTrigger
            data-testid="availability-window"
            aria-label="Availability window"
            className="h-8 w-[150px] text-xs"
          >
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
      </CardHeader>
      <CardContent>
        {error !== null && rows.length === 0 ? (
          <p className="text-sm text-red-600">Failed to load availability: {error}</p>
        ) : loading && rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Loading availability…</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead className="text-right">Uptime</TableHead>
                <TableHead className="text-right">Downtime</TableHead>
                <TableHead className="text-right">Outages</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.device_id} data-testid="availability-row">
                  <TableCell>
                    <Link
                      to={`/devices/${row.device_id}`}
                      className="font-medium hover:underline"
                    >
                      {nameOf(row.device_id)}
                    </Link>
                    {/* Say so when the figure covers less than the window. */}
                    {row.uptime_percent !== null &&
                      row.observed_seconds < windowSeconds * 0.99 && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          monitored for {formatDuration(row.observed_seconds)}
                        </span>
                      )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.uptime_percent === null
                      ? '—'
                      : `${row.uptime_percent.toFixed(2)}%`}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.downtime_seconds === 0
                      ? '—'
                      : formatDuration(row.downtime_seconds)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.outages}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
