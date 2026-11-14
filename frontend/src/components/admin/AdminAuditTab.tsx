import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
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
    <div className="space-y-4 pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground" data-testid="audit-count">
          {total === 0
            ? 'No events'
            : `Showing ${offset + 1}–${offset + items.length} of ${total}`}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <form onSubmit={applyActor} className="flex items-center gap-2">
            <Input
              data-testid="audit-actor-filter"
              aria-label="Filter by user"
              placeholder="User (exact name)"
              value={actorInput}
              onChange={(event) => setActorInput(event.target.value)}
              className="h-8 w-[170px] text-xs"
            />
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
        <p className="text-sm text-red-600">
          Failed to load the audit log: {error}
        </p>
      )}

      <div className="rounded-md border">
        <Table>
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
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  Loading the audit log…
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow data-testid="audit-empty">
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  {filtered ? 'No events match the filter.' : 'Nothing recorded yet.'}
                </TableCell>
              </TableRow>
            ) : (
              items.map((event) => (
                <TableRow key={event.id} data-testid="audit-row">
                  <TableCell className="whitespace-nowrap text-xs">
                    {formatDateTime(event.ts)}
                  </TableCell>
                  <TableCell className="max-w-[160px] truncate" title={event.actor}>
                    {event.actor}
                  </TableCell>
                  <TableCell
                    className={
                      // Failed and blocked logins are the ones to look for.
                      event.action === 'auth.login_failed' ||
                      event.action === 'auth.login_blocked'
                        ? 'font-mono text-xs font-semibold text-red-600'
                        : 'font-mono text-xs'
                    }
                  >
                    {event.action}
                  </TableCell>
                  <TableCell className="max-w-[200px] truncate" title={event.target ?? ''}>
                    {event.target ?? '—'}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {event.ip ?? '—'}
                  </TableCell>
                  <TableCell className="max-w-[280px] truncate text-xs text-muted-foreground" title={describe(event.details)}>
                    {describe(event.details)}
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
