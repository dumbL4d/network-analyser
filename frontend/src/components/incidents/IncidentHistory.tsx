import { ArrowRight, ChevronLeft, ChevronRight, History } from 'lucide-react'
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
import { Card } from '@/components/ui/card'
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[11px] text-slate-500">
          <History className="h-3.5 w-3.5 text-slate-400" />
          {total === 0
            ? 'No incidents recorded'
            : `Showing ${offset + 1}–${offset + items.length} of ${total}`}
        </div>
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
            className="h-8 w-[164px] text-[11px]"
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
        <Card className="border-rose-200 p-4 text-[12px] text-rose-700">
          Failed to load incidents: {error}
        </Card>
      )}

      <Card className="overflow-hidden">
        <Table className="table-density">
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">#</TableHead>
              <TableHead>Root device</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Opened</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead className="text-right">Peak affected</TableHead>
              <TableHead className="w-24 text-right">Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && items.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-10 text-center text-slate-500"
                >
                  Loading incidents…
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow data-testid="history-empty">
                <TableCell
                  colSpan={7}
                  className="py-10 text-center text-slate-500"
                >
                  No incidents recorded{filter === 'all' ? '' : ' in this state'}.
                </TableCell>
              </TableRow>
            ) : (
              items.map((incident) => (
                <TableRow key={incident.id} data-testid="history-row">
                  <TableCell className="mono text-[11px] text-slate-400">
                    {incident.id}
                  </TableCell>
                  <TableCell>
                    <span className="text-[12px] font-semibold text-slate-800">
                      {nameOf(incident.root_device_id)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <IncidentStateBadge state={incident.state} />
                  </TableCell>
                  <TableCell className="mono text-[11px] text-slate-500">
                    {formatDateTime(incident.opened_at)}
                  </TableCell>
                  <TableCell>
                    <span className="mono text-[11px] text-slate-600">
                      {formatDuration(
                        secondsBetween(incident.opened_at, incident.resolved_at),
                      )}
                    </span>
                    {incident.resolved_at === null && (
                      <span className="ml-1.5 rounded bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-amber-700">
                        Ongoing
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <span className="mono inline-flex min-w-6 justify-center rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-700">
                      {incident.peak_affected_count}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <Link
                      to={`/incidents/${incident.id}`}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:underline"
                    >
                      Timeline
                      <ArrowRight className="h-3 w-3" />
                    </Link>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <div className="flex items-center justify-between">
        <p className="mono text-[10px] text-slate-400">
          Page {Math.floor(offset / PAGE_SIZE) + 1} of{' '}
          {Math.max(1, Math.ceil(total / PAGE_SIZE))}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}
