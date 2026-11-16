import {
  ArrowLeft,
  Clock,
  Layers,
  MessageSquarePlus,
  ShieldAlert,
  Timer,
  Users,
  Waypoints,
} from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'

import IncidentStateBadge from '@/components/incidents/IncidentStateBadge'
import KpiCard from '@/components/ui/kpi-card'
import PageHeader from '@/components/ui/page-header'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/contexts/AuthContext'
import { useDevices } from '@/hooks/useDevices'
import { useIncidentDetail } from '@/hooks/useIncidentRecords'
import { acknowledgeIncident, addIncidentNote } from '@/lib/api'
import { formatDateTime, formatDuration, secondsBetween } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { IncidentEvent, IncidentEventType } from '@/types/incident'

function BackToIncidents() {
  return (
    <Link
      to="/incidents"
      className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-500 transition-colors hover:text-slate-900"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to Incidents
    </Link>
  )
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 text-[12px]">
      <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.1em] text-slate-400">
        {label}
      </span>
      <span className="text-right font-medium text-slate-700">{children}</span>
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

const EVENT_TONE: Record<IncidentEventType, { dot: string; badge: string }> = {
  opened: {
    dot: 'bg-rose-500',
    badge: 'border-rose-200 bg-rose-50 text-rose-700',
  },
  affected_changed: {
    dot: 'bg-amber-500',
    badge: 'border-amber-200 bg-amber-50 text-amber-700',
  },
  acknowledged: {
    dot: 'bg-blue-500',
    badge: 'border-blue-200 bg-blue-50 text-blue-700',
  },
  note: {
    dot: 'bg-slate-400',
    badge: 'border-slate-200 bg-slate-50 text-slate-600',
  },
  resolved: {
    dot: 'bg-emerald-500',
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  },
}

export default function IncidentDetailView() {
  const { incidentId = '' } = useParams<{ incidentId: string }>()
  const { role } = useAuth()
  const { devices } = useDevices()
  const {
    data: incident,
    loading,
    error,
    refresh,
  } = useIncidentDetail(Number(incidentId))

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
      <div className="page-shell">
        <BackToIncidents />
        {loading ? (
          <Card className="mt-5 p-10 text-center text-[12px] text-slate-500">
            Loading incident…
          </Card>
        ) : (
          <Card className="mt-5 border-rose-200 p-6 text-[12px] text-rose-700">
            Failed to load incident: {error ?? 'Unknown error'}
          </Card>
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
  const detectionSeconds = secondsBetween(
    incident.first_failure_at,
    incident.opened_at,
  )
  const durationSeconds = secondsBetween(
    incident.opened_at,
    incident.resolved_at,
  )
  const isOngoing = incident.resolved_at === null

  return (
    <div className="page-shell">
      <BackToIncidents />

      <div className="mt-3">
        <PageHeader
          eyebrow={
            <span className="label-caps flex items-center gap-1.5">
              <ShieldAlert className="h-3 w-3" /> Incident #{incident.id}
              <span className="h-1 w-1 rounded-full bg-slate-300" />
              Root-cause analysis
            </span>
          }
          title={`Incident #${incident.id}: ${nameOf(incident.root_device_id)}`}
          description={`Opened ${formatDateTime(incident.opened_at)} · first failing probe ${formatDateTime(incident.first_failure_at)}`}
          actions={<IncidentStateBadge state={incident.state} />}
        />
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiCard
          label="Duration"
          value={formatDuration(durationSeconds)}
          hint={isOngoing ? 'Ongoing incident' : 'Opened to resolved'}
          icon={Timer}
          tone={isOngoing ? 'rose' : 'emerald'}
        />
        <KpiCard
          label="Detection delay"
          value={formatDuration(detectionSeconds)}
          hint="First failing probe to confirmed incident"
          icon={Clock}
          tone="blue"
        />
        <KpiCard
          label="Peak affected"
          value={incident.peak_affected_count}
          hint="Most downstream devices affected at once"
          icon={Layers}
          tone={incident.peak_affected_count > 0 ? 'amber' : 'neutral'}
        />
        <KpiCard
          label="Timeline events"
          value={incident.events.length}
          hint="Recorded changes since the incident opened"
          icon={Waypoints}
          tone="violet"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <p className="text-[13px] font-semibold text-slate-900">
                  Incident details
                </p>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  Root cause and impact footprint
                </p>
              </div>
              <IncidentStateBadge state={incident.state} />
            </div>
            <div className="divide-y divide-slate-100 px-5 py-1">
              <InfoRow label="Root device">
                <Link
                  to={`/devices/${incident.root_device_id}`}
                  className="font-medium text-blue-600 hover:underline"
                >
                  {nameOf(incident.root_device_id)}
                </Link>
              </InfoRow>
              <InfoRow label="First failing probe">
                {formatDateTime(incident.first_failure_at)}
              </InfoRow>
              <InfoRow label="Opened">
                {formatDateTime(incident.opened_at)}
              </InfoRow>
              <InfoRow label="Detection delay">
                {formatDuration(detectionSeconds)}
              </InfoRow>
              <InfoRow label="Acknowledged">
                {incident.acknowledged_at === null
                  ? '—'
                  : `${formatDateTime(incident.acknowledged_at)} by ${incident.acknowledged_by}`}
              </InfoRow>
              <InfoRow label="Resolved">
                {formatDateTime(incident.resolved_at)}
              </InfoRow>
              <InfoRow label="Duration">
                {formatDuration(durationSeconds)}
                {isOngoing && (
                  <span className="text-slate-400"> (ongoing)</span>
                )}
              </InfoRow>
              <InfoRow label="Peak affected">
                {incident.peak_affected_count}
              </InfoRow>
              <InfoRow label="Affected devices">
                {incident.affected_device_ids.length === 0
                  ? 'None'
                  : incident.affected_device_ids.map(nameOf).join(', ')}
              </InfoRow>
            </div>
          </Card>

          {isAdmin && (
            <Card data-testid="incident-actions" className="overflow-hidden">
              <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
                  <MessageSquarePlus className="h-3.5 w-3.5" />
                </span>
                <div>
                  <p className="text-[13px] font-semibold text-slate-900">
                    Actions
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Acknowledge the incident or leave a note on the timeline.
                  </p>
                </div>
              </div>
              <div className="space-y-4 p-5">
                {incident.state === 'open' && (
                  <Button
                    data-testid="acknowledge-button"
                    disabled={busy}
                    onClick={() =>
                      void run(() => acknowledgeIncident(incident.id))
                    }
                  >
                    Acknowledge
                  </Button>
                )}
                <form onSubmit={handleAddNote} className="space-y-2">
                  <Label htmlFor="incident-note">
                    Add a note to the timeline
                  </Label>
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
                  <p
                    data-testid="incident-action-error"
                    className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700"
                  >
                    {actionError}
                  </p>
                )}
              </div>
            </Card>
          )}
        </div>

        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <p className="text-[13px] font-semibold text-slate-900">
                Timeline
              </p>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Oldest first · {incident.events.length} events
              </p>
            </div>
            <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
              <Users className="h-4 w-4" />
            </span>
          </div>
          <div className="p-5">
            <ol data-testid="incident-timeline" className="space-y-4">
              {incident.events.map((event, index) => {
                const { label, text } = describeEvent(event, nameOf)
                const tone = EVENT_TONE[event.type]
                return (
                  <li
                    key={event.id}
                    data-testid={`timeline-${event.type}`}
                    className="relative flex gap-3"
                  >
                    <div className="flex flex-col items-center">
                      <span
                        className={cn(
                          'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 border-white text-[9px] font-semibold text-white shadow-sm',
                          tone.dot,
                        )}
                      >
                        {index + 1}
                      </span>
                      {index < incident.events.length - 1 && (
                        <span className="mt-1 w-px flex-1 bg-slate-200" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1 pb-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            'rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]',
                            tone.badge,
                          )}
                        >
                          {label}
                        </span>
                        <span className="mono text-[10px] text-slate-400">
                          {formatDateTime(event.ts)}
                        </span>
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-600">
                        {text}
                      </p>
                    </div>
                  </li>
                )
              })}
            </ol>
          </div>
        </Card>
      </div>
    </div>
  )
}
