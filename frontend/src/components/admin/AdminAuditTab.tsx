import { ChevronLeft, ChevronRight, ScrollText, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
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
import { usePolled } from '@/hooks/usePolled'
import { fetchAudit } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 25
const AUDIT_POLL_MS = 15_000
const ALL_ACTIONS = 'all'

// Every action the backend records (docs/security.md has what each means).
const ACTIONS = [
  'auth.login',
  'auth.login_failed',
  'auth.login_blocked',
  'auth.password_changed',
  'user.created',
  'user.deleted',
  'device.created',
  'device.updated',
  'device.deleted',
  'link.created',
  'link.deleted',
  'settings.updated',
  'incident.acknowledged',
  'incident.note_added',
  'chaos.fail',
  'chaos.degrade',
  'chaos.flap',
  'chaos.scenario',
  'chaos.restore_all',
]

function show(value: unknown): string {
  if (value === null || value === '') return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** An event's details on one line; a change as "field: old → new". */
function describe(details: Record<string, unknown>): string {
  const { changes, ...rest } = details
  const parts = Object.entries(rest).map(
    ([key, value]) => `${key}: ${show(value)}`,
  )
  if (typeof changes === 'object' && changes !== null) {
    for (const [field, change] of Object.entries(
      changes as Record<string, { from: unknown; to: unknown }>,
    )) {
      parts.push(`${field}: ${show(change.from)} → ${show(change.to)}`)
    }
  }
  return parts.join(', ')
}

/**
 * Admin tab for the audit log: who did what, when, and from which address.
 * Read only, newest first, refreshed every 15 s.
 */
export default function AdminAuditTab() {
  const [actorInput, setActorInput] = useState('')
  const [actor, setActor] = useState('')
  const [action, setAction] = useState(ALL_ACTIONS)
  const [offset, setOffset] = useState(0)
  const {
    data: page,
    loading,
    error,
  } = usePolled(
    () =>
      fetchAudit({
        actor,
        action: action === ALL_ACTIONS ? undefined : action,
        limit: PAGE_SIZE,
        offset,
      }),
    `${actor}|${action}|${offset}`,
    AUDIT_POLL_MS,
  )

  const total = page?.total ?? 0
  const items = page?.items ?? []
  const filtered = actor !== '' || action !== ALL_ACTIONS

  const applyActor = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setActor(actorInput.trim())
    setOffset(0)
  }

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
              <ScrollText className="h-3.5 w-3.5" />
            </span>
            <div>
              <p className="text-[13px] font-semibold text-slate-900">
                Audit log
              </p>
              <p
                className="text-[11px] text-slate-500"
                data-testid="audit-count"
              >
                {total === 0
                  ? 'No events'
                  : `Showing ${offset + 1}–${offset + items.length} of ${total}`}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <form onSubmit={applyActor} className="flex items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <Input
                  data-testid="audit-actor-filter"
                  aria-label="Filter by user"
                  placeholder="User (exact name)"
                  value={actorInput}
                  onChange={(event) => setActorInput(event.target.value)}
                  className="h-8 w-[170px] pl-8 text-xs"
                />
              </div>
              <Button type="submit" variant="outline" size="sm">
                Apply
              </Button>
            </form>
            <Select
              value={action}
              onValueChange={(next) => {
                setAction(next)
                setOffset(0)
              }}
            >
              <SelectTrigger
                data-testid="audit-action-filter"
                aria-label="Filter by action"
                className="h-8 w-[200px] text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_ACTIONS}>All actions</SelectItem>
                {ACTIONS.map((name) => (
                  <SelectItem key={name} value={name}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {error !== null && (
          <p className="border-b border-rose-100 bg-rose-50/60 px-5 py-2.5 text-[12px] text-rose-700">
            Failed to load the audit log: {error}
          </p>
        )}

        <Table className="table-density">
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Address</TableHead>
              <TableHead>Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && items.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-[12px] text-slate-500"
                >
                  Loading the audit log…
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow data-testid="audit-empty">
                <TableCell
                  colSpan={6}
                  className="py-10 text-center text-[12px] text-slate-500"
                >
                  {filtered
                    ? 'No events match the filter.'
                    : 'Nothing recorded yet.'}
                </TableCell>
              </TableRow>
            ) : (
              items.map((event) => {
                const securityEvent =
                  event.action === 'auth.login_failed' ||
                  event.action === 'auth.login_blocked'
                return (
                  <TableRow key={event.id} data-testid="audit-row">
                    <TableCell className="mono whitespace-nowrap text-[10px] text-slate-400">
                      {formatDateTime(event.ts)}
                    </TableCell>
                    <TableCell
                      className="max-w-[160px] truncate text-[12px] text-slate-700"
                      title={event.actor}
                    >
                      {event.actor}
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          'mono rounded-md border px-1.5 py-0.5 text-[10px] font-medium',
                          securityEvent
                            ? 'border-rose-200 bg-rose-50 font-semibold text-rose-700'
                            : 'border-slate-200 bg-slate-50 text-slate-600',
                        )}
                      >
                        {event.action}
                      </span>
                    </TableCell>
                    <TableCell
                      className="max-w-[200px] truncate text-[11px] text-slate-500"
                      title={event.target ?? ''}
                    >
                      {event.target ?? '—'}
                    </TableCell>
                    <TableCell className="mono text-[11px] text-slate-500">
                      {event.ip ?? '—'}
                    </TableCell>
                    <TableCell
                      className="max-w-[280px] truncate text-[11px] text-slate-400"
                      title={describe(event.details)}
                    >
                      {describe(event.details)}
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>

        <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3">
          <p className="text-[10px] text-slate-400">
            Newest first · refreshed every 15 s
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
      </Card>
    </div>
  )
}
