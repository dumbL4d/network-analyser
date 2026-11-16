import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'

import IncidentStateBadge from '@/components/incidents/IncidentStateBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/contexts/AuthContext'
import { useDevices } from '@/hooks/useDevices'
import { useIncidentDetail } from '@/hooks/useIncidentRecords'
import { acknowledgeIncident, addIncidentNote } from '@/lib/api'
import { formatDateTime, formatDuration, secondsBetween } from '@/lib/format'
import type { IncidentEvent } from '@/types/incident'

function BackToIncidents() {
  return (
    <Link
      to="/incidents"
      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      ← Back to Incidents
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

/** A timeline entry in words. `nameOf` turns a device id into its name. */
function describeEvent(
  event: IncidentEvent,
  nameOf: (deviceId: string) => string,
): { label: string; text: string } {
  const details = event.details
  const names = (value: unknown) =>
    Array.isArray(value) ? value.map((id) => nameOf(String(id))) : []

  switch (event.type) {
    case 'opened': {
      const affected = names(details.affected)
      const parts = [`The root device is ${String(details.status ?? 'unhealthy')}.`]
      if (affected.length > 0) {
        parts.push(`Affected downstream: ${affected.join(', ')}.`)
      }
      if (details.promoted_from_collateral === true) {
        parts.push('It was already down behind another outage.')
      }
      return { label: 'Incident opened', text: parts.join(' ') }
    }
    case 'affected_changed': {
      const added = names(details.added)
      const removed = names(details.removed)
      const parts = []
      if (added.length > 0) parts.push(`Now also affected: ${added.join(', ')}.`)
      if (removed.length > 0) parts.push(`No longer affected: ${removed.join(', ')}.`)
      parts.push(`${String(details.affected_count)} affected in total.`)
      return { label: 'Affected devices changed', text: parts.join(' ') }
    }
    case 'acknowledged':
      return { label: 'Acknowledged', text: `By ${String(details.by)}.` }
    case 'note':
      return { label: `Note by ${String(details.by)}`, text: String(details.text) }
    case 'resolved': {
      const parts = [
        details.reason === 'device_deleted'
          ? 'The root device was deleted.'
          : 'The root device is healthy again.',
      ]
      if (details.after_restart === true) {
        parts.push(
          'Seen on the first poll after a backend restart, so it may have recovered earlier.',
        )
      }
      return { label: 'Resolved', text: parts.join(' ') }
    }
  }
}

export default function IncidentDetailView() {
  const { incidentId = '' } = useParams<{ incidentId: string }>()
  const { role } = useAuth()
  const { devices } = useDevices()
  const { data: incident, loading, error, refresh } = useIncidentDetail(Number(incidentId))

  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId

  // Run an admin action, then re-fetch the incident so the timeline updates.
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      refresh()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  if (incident === null) {
    return (
      <div className="p-8">
        <BackToIncidents />
        {loading ? (
          <p className="mt-6 text-sm text-muted-foreground">Loading incident…</p>
        ) : (
          <p className="mt-6 text-sm text-red-600">
            Failed to load incident: {error ?? 'Unknown error'}
          </p>
        )}
      </div>
    )
  }

  const handleAddNote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(async () => {
      await addIncidentNote(incident.id, note)
      setNote('')
    })
  }

  const isAdmin = role === 'admin'

  return (
    <div className="p-8">
      <BackToIncidents />
      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle>
                Incident #{incident.id}: {nameOf(incident.root_device_id)}
              </CardTitle>
              <IncidentStateBadge state={incident.state} />
            </CardHeader>
            <CardContent className="divide-y">
              <InfoRow label="Root device">
                <Link
                  to={`/devices/${incident.root_device_id}`}
                  className="text-blue-600 hover:underline"
                >
                  {nameOf(incident.root_device_id)}
                </Link>
              </InfoRow>
              <InfoRow label="First failing probe">
                {formatDateTime(incident.first_failure_at)}
              </InfoRow>
              <InfoRow label="Opened">{formatDateTime(incident.opened_at)}</InfoRow>
              <InfoRow label="Detection delay">
                {formatDuration(
                  secondsBetween(incident.first_failure_at, incident.opened_at),
                )}
              </InfoRow>
              <InfoRow label="Acknowledged">
                {incident.acknowledged_at === null
                  ? '—'
                  : `${formatDateTime(incident.acknowledged_at)} by ${incident.acknowledged_by}`}
              </InfoRow>
              <InfoRow label="Resolved">{formatDateTime(incident.resolved_at)}</InfoRow>
              <InfoRow label="Duration">
                {formatDuration(secondsBetween(incident.opened_at, incident.resolved_at))}
                {incident.resolved_at === null && ' (ongoing)'}
              </InfoRow>
              <InfoRow label="Peak affected">{incident.peak_affected_count}</InfoRow>
              <InfoRow label="Affected devices">
                {incident.affected_device_ids.length === 0
                  ? 'None'
                  : incident.affected_device_ids.map(nameOf).join(', ')}
              </InfoRow>
            </CardContent>
          </Card>

          {isAdmin && (
            <Card data-testid="incident-actions">
              <CardHeader>
                <CardTitle className="text-base">Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {incident.state === 'open' && (
                  <Button
                    data-testid="acknowledge-button"
                    disabled={busy}
                    onClick={() => void run(() => acknowledgeIncident(incident.id))}
                  >
                    Acknowledge
                  </Button>
                )}
                <form onSubmit={handleAddNote} className="space-y-2">
                  <Label htmlFor="incident-note">Add a note to the timeline</Label>
                  <Textarea
                    id="incident-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={3}
                    maxLength={2000}
                    placeholder="What was found or done"
                    required
                  />
                  <Button
                    type="submit"
                    variant="outline"
                    size="sm"
                    disabled={busy || note.trim() === ''}
                  >
                    Add note
                  </Button>
                </form>
                {actionError !== null && (
                  <p data-testid="incident-action-error" className="text-sm text-red-600">
                    {actionError}
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <ol data-testid="incident-timeline" className="space-y-4">
              {incident.events.map((event) => {
                const { label, text } = describeEvent(event, nameOf)
                return (
                  <li
                    key={event.id}
                    data-testid={`timeline-${event.type}`}
                    className="border-l-2 border-muted pl-4"
                  >
                    <p className="text-xs text-muted-foreground">
                      {formatDateTime(event.ts)}
                    </p>
                    <p className="text-sm font-medium">{label}</p>
                    <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                      {text}
                    </p>
                  </li>
                )
              })}
            </ol>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
