import { useState } from 'react'
import { Link } from 'react-router-dom'

import IncidentStateBadge from '@/components/incidents/IncidentStateBadge'
import { Button } from '@/components/ui/button'
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
import { useDevices } from '@/hooks/useDevices'
import { useIncidentHistory } from '@/hooks/useIncidentRecords'
import { formatDateTime, formatDuration, secondsBetween } from '@/lib/format'
import type { IncidentState } from '@/types/incident'

const PAGE_SIZE = 20

type StateFilter = 'all' | IncidentState

const FILTERS: { value: StateFilter; label: string }[] = [
  { value: 'all', label: 'All states' },
  { value: 'open', label: 'Open' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
]

/** The History tab: every stored incident, most recently opened first. */
export default function IncidentHistory() {
  const [filter, setFilter] = useState<StateFilter>('all')
  const [offset, setOffset] = useState(0)
  const { devices } = useDevices()
  const {
    data: page,
    loading,
    error,
  } = useIncidentHistory(filter === 'all' ? [] : [filter], PAGE_SIZE, offset)

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId
  const total = page?.total ?? 0
  const items = page?.items ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total === 0
            ? 'No incidents'
            : `Showing ${offset + 1}–${offset + items.length} of ${total}`}
        </p>
        <Select
          value={filter}
          onValueChange={(next) => {
            setFilter(next as StateFilter)
            setOffset(0)
          }}
        >
          <SelectTrigger
            data-testid="history-state-filter"
            aria-label="Filter by state"
            className="h-8 w-[160px] text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FILTERS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {error !== null && (
        <p className="text-sm text-red-600">Failed to load incidents: {error}</p>
      )}

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>Root device</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Opened</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead className="text-right">Peak affected</TableHead>
              <TableHead className="text-right">Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  Loading incidents…
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow data-testid="history-empty">
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  No incidents recorded{filter === 'all' ? '' : ' in this state'}.
                </TableCell>
              </TableRow>
            ) : (
              items.map((incident) => (
                <TableRow key={incident.id} data-testid="history-row">
                  <TableCell className="font-mono text-xs">{incident.id}</TableCell>
                  <TableCell>{nameOf(incident.root_device_id)}</TableCell>
                  <TableCell>
                    <IncidentStateBadge state={incident.state} />
                  </TableCell>
                  <TableCell>{formatDateTime(incident.opened_at)}</TableCell>
                  <TableCell>
                    {formatDuration(
                      secondsBetween(incident.opened_at, incident.resolved_at),
                    )}
                    {incident.resolved_at === null && ' (ongoing)'}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {incident.peak_affected_count}
                  </TableCell>
                  <TableCell className="text-right">
                    <Link
                      to={`/incidents/${incident.id}`}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      Timeline
                    </Link>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Next
        </Button>
      </div>
    </div>
  )
}
