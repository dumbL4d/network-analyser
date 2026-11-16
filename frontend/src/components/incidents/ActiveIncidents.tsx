import { useState } from 'react'
import { Link } from 'react-router-dom'

import GuidedFixPlaybook from '@/components/incidents/GuidedFixPlaybook'
import IncidentStateBadge from '@/components/incidents/IncidentStateBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useIncidentHistory } from '@/hooks/useIncidentRecords'
import { useIncidents } from '@/hooks/useIncidents'
import { formatDateTime } from '@/lib/format'
import type { DeviceOut } from '@/types/device'
import type { IncidentOut, IncidentRecord } from '@/types/incident'

// Only unhealthy statuses produce incidents, so the live `status` value is
// always one of the playbook states. Passed through as-is rather than assuming
// "down": a device that is "degraded" (warn-threshold latency) fetches the
// DEGRADED playbook variant, not the down one.
type GuidedFixState = 'down' | 'degraded'

function IncidentMeta({ incident }: { incident: IncidentOut }) {
  return (
    <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-muted-foreground sm:grid-cols-4">
      <li>IP: {incident.device.ip}</li>
      <li>Zone: {incident.device.zone}</li>
      <li>
        Latency:{' '}
        {incident.latency_ms === null
          ? '—'
          : `${incident.latency_ms.toFixed(2)} ms`}
      </li>
      <li className="capitalize">Status: {incident.status}</li>
    </ul>
  )
}

function downstreamSummary(devices: DeviceOut[]) {
  return (
    <p className="mt-3 text-sm text-muted-foreground">
      Affects {devices.length} other device
      {devices.length === 1 ? '' : 's'}:{' '}
      {devices.map((device) => device.name).join(', ')}
    </p>
  )
}

function IncidentCard({
  incident,
  record,
  expanded,
  onToggle,
}: {
  incident: IncidentOut
  /** The stored incident for this root cause, once the tracker has opened it. */
  record: IncidentRecord | undefined
  expanded: boolean
  onToggle: () => void
}) {
  const isRootCause = incident.category === 'root_cause'

  return (
    <Card
      data-testid="incident-card"
      className={isRootCause ? 'border-red-200' : 'border-amber-200'}
    >
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">{incident.device.name}</CardTitle>
            <span
              data-testid="incident-category"
              className={
                isRootCause
                  ? 'rounded-full bg-red-500 px-2 py-0.5 text-xs font-semibold text-white'
                  : 'rounded-full bg-amber-500 px-2 py-0.5 text-xs font-semibold text-white'
              }
            >
              {isRootCause ? 'ROOT CAUSE' : 'COLLATERAL'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={onToggle}>
            {expanded ? 'Hide guided fix' : 'Guided fix'}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <IncidentMeta incident={incident} />
        {record !== undefined && (
          <p
            data-testid="incident-record"
            className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground"
          >
            <IncidentStateBadge state={record.state} />
            <span>
              Incident #{record.id}, opened {formatDateTime(record.opened_at)}
              {record.acknowledged_by !== null &&
                `, acknowledged by ${record.acknowledged_by}`}
            </span>
            <Link
              to={`/incidents/${record.id}`}
              className="text-blue-600 hover:underline"
            >
              Timeline
            </Link>
          </p>
        )}
        {isRootCause && incident.downstream_affected.length > 0 && (
          <div data-testid="downstream-summary">
            {downstreamSummary(incident.downstream_affected)}
          </div>
        )}
        {expanded && (
          <GuidedFixPlaybook
            key={`${incident.device.id}:${incident.status}`}
            deviceType={incident.device.type}
            state={incident.status as GuidedFixState}
          />
        )}
      </CardContent>
    </Card>
  )
}

/**
 * The Active tab: the live root-cause / collateral set, as before. Each root
 * cause also shows its stored incident (state, when it opened, a link to the
 * timeline) once the backend's tracker has opened one.
 */
export default function ActiveIncidents() {
  const { incidents, loading, error } = useIncidents()
  const { data: unresolved } = useIncidentHistory(['open', 'acknowledged'], 200, 0)
  // Expanded-card state keyed by device id so it survives re-renders from the
  // polling hook. A set keeps entries for resolved incidents, but the cards
  // themselves are driven purely by the live incidents array -- a resolved
  // incident's card (and any expansion) simply disappears on the next poll.
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const recordByDevice = new Map(
    (unresolved?.items ?? []).map((record) => [record.root_device_id, record]),
  )

  const toggle = (deviceId: string) => {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(deviceId)) next.delete(deviceId)
      else next.add(deviceId)
      return next
    })
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading incidents…</p>
  }

  if (error !== null) {
    return <p className="text-sm text-red-600">Failed to load incidents: {error}</p>
  }

  if (incidents.length === 0) {
    return (
      <Card data-testid="incidents-empty">
        <CardContent className="p-8 text-center">
          <p className="text-sm text-muted-foreground">All monitored devices healthy</p>
        </CardContent>
      </Card>
    )
  }

  const rootCauses = incidents.filter((i) => i.category === 'root_cause')
  const collateral = incidents.filter((i) => i.category === 'collateral')

  return (
    <div>
      <p className="mb-6 text-sm text-muted-foreground">
        Root causes are the actionable failures; collateral devices are affected
        as a consequence.
      </p>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-red-600">
          Root causes
        </h2>
        <div className="space-y-4">
          {rootCauses.map((incident) => (
            <IncidentCard
              key={incident.device.id}
              incident={incident}
              record={recordByDevice.get(incident.device.id)}
              expanded={expanded.has(incident.device.id)}
              onToggle={() => toggle(incident.device.id)}
            />
          ))}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-amber-600">
          Collateral
        </h2>
        <p className="mb-3 text-xs text-muted-foreground">
          These will likely auto-recover once the root cause is fixed.
        </p>
        <div className="space-y-4">
          {collateral.map((incident) => (
            <IncidentCard
              key={incident.device.id}
              incident={incident}
              record={undefined}
              expanded={expanded.has(incident.device.id)}
              onToggle={() => toggle(incident.device.id)}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
