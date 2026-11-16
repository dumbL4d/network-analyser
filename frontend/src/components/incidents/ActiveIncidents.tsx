import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ShieldAlert,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import GuidedFixPlaybook from '@/components/incidents/GuidedFixPlaybook'
import IncidentStateBadge from '@/components/incidents/IncidentStateBadge'
import DeviceTypeIcon from '@/components/ui/device-type-icon'
import StatusBadge from '@/components/ui/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useIncidentHistory } from '@/hooks/useIncidentRecords'
import { useIncidents } from '@/hooks/useIncidents'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { DeviceOut, DeviceStatus } from '@/types/device'
import type { IncidentOut, IncidentRecord } from '@/types/incident'

// Only unhealthy statuses produce incidents, so the live `status` value is
// always one of the playbook states. Passed through as-is rather than assuming
// "down": a device that is "degraded" (warn-threshold latency) fetches the
// DEGRADED playbook variant, not the down one.
type GuidedFixState = 'down' | 'degraded'

function IncidentMeta({ incident }: { incident: IncidentOut }) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 sm:grid-cols-4">
      <div className="bg-white px-3 py-2">
        <p className="text-[9px] font-medium uppercase tracking-[0.1em] text-slate-400">
          IP address
        </p>
        <p className="mono mt-1 text-[11px] text-slate-700">{incident.device.ip}</p>
      </div>
      <div className="bg-white px-3 py-2">
        <p className="text-[9px] font-medium uppercase tracking-[0.1em] text-slate-400">
          Zone
        </p>
        <p className="mt-1 text-[11px] font-medium text-slate-700">
          {incident.device.zone}
        </p>
      </div>
      <div className="bg-white px-3 py-2">
        <p className="text-[9px] font-medium uppercase tracking-[0.1em] text-slate-400">
          Latency
        </p>
        <p className="mono mt-1 text-[11px] text-slate-700">
          {incident.latency_ms === null
            ? '—'
            : `${incident.latency_ms.toFixed(2)} ms`}
        </p>
      </div>
      <div className="bg-white px-3 py-2">
        <p className="text-[9px] font-medium uppercase tracking-[0.1em] text-slate-400">
          Confirmed state
        </p>
        <p className="mt-1 text-[11px] font-medium capitalize text-slate-700">
          {incident.status}
        </p>
      </div>
    </div>
  )
}

function downstreamSummary(devices: DeviceOut[]) {
  return (
    <div className="mt-3 rounded-lg border border-rose-100 bg-rose-50/60 p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-rose-700">
        <ArrowRight className="h-3 w-3" />
        Downstream impact
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-rose-800/80">
        Affects {devices.length} other device
        {devices.length === 1 ? '' : 's'}:{' '}
        {devices.map((device) => device.name).join(', ')}
      </p>
    </div>
  )
}

function CategoryBadge({ category }: { category: IncidentOut['category'] }) {
  const root = category === 'root_cause'
  return (
    <span
      data-testid="incident-category"
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]',
        root
          ? 'border-rose-200 bg-rose-50 text-rose-700'
          : 'border-amber-200 bg-amber-50 text-amber-700',
      )}
    >
      {root ? (
        <ShieldAlert className="h-2.5 w-2.5" />
      ) : (
        <TriangleAlert className="h-2.5 w-2.5" />
      )}
      {root ? 'Root cause' : 'Collateral'}
    </span>
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
      className={cn(
        'relative overflow-hidden border-slate-200 transition-shadow hover:shadow-float',
        isRootCause ? 'border-l-[3px] border-l-rose-500' : 'border-l-[3px] border-l-amber-400',
      )}
    >
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className={cn(
                'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border',
                isRootCause
                  ? 'border-rose-100 bg-rose-50 text-rose-600'
                  : 'border-amber-100 bg-amber-50 text-amber-600',
              )}
            >
              <DeviceTypeIcon type={incident.device.type} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="truncate">{incident.device.name}</CardTitle>
                <CategoryBadge category={incident.category} />
                <StatusBadge status={incident.status as DeviceStatus} />
              </div>
              <p className="mono mt-1 text-[10px] text-slate-400">
                {incident.device.id} · {incident.device.type}
              </p>
            </div>
          </div>
          <Button
            variant={expanded ? 'soft' : 'outline'}
            size="sm"
            onClick={onToggle}
            className="shrink-0"
          >
            {expanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
            {expanded ? 'Hide guided fix' : 'Guided fix'}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <IncidentMeta incident={incident} />
        {record !== undefined && (
          <p
            data-testid="incident-record"
            className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500"
          >
            <IncidentStateBadge state={record.state} />
            <span>
              Incident #{record.id}, opened {formatDateTime(record.opened_at)}
              {record.acknowledged_by !== null &&
                `, acknowledged by ${record.acknowledged_by}`}
            </span>
            <Link
              to={`/incidents/${record.id}`}
              className="inline-flex items-center gap-1 font-medium text-blue-600 hover:underline"
            >
              Timeline <ArrowRight className="h-3 w-3" />
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
    return (
      <Card className="p-10 text-center text-[12px] text-slate-500">
        Loading incidents…
      </Card>
    )
  }

  if (error !== null) {
    return (
      <Card className="border-rose-200 p-6 text-[12px] text-rose-700">
        Failed to load incidents: {error}
      </Card>
    )
  }

  if (incidents.length === 0) {
    return (
      <Card data-testid="incidents-empty" className="overflow-hidden">
        <CardContent className="flex flex-col items-center justify-center px-6 py-14 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-600">
            <CheckCircle2 className="h-6 w-6" />
          </span>
          <p className="mt-4 text-[14px] font-semibold text-slate-900">
            No active incidents
          </p>
          <p className="mt-1 text-[12px] text-slate-500">
            All monitored devices are healthy.
          </p>
        </CardContent>
      </Card>
    )
  }

  const rootCauses = incidents.filter((i) => i.category === 'root_cause')
  const collateral = incidents.filter((i) => i.category === 'collateral')

  return (
    <div>
      <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-blue-200 bg-blue-50/60 px-3.5 py-3">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
        <p className="text-[11px] leading-relaxed text-blue-800">
          Root causes are the actionable failures; collateral devices are
          affected as a consequence. Fix the root cause first to avoid duplicate
          remediation.
        </p>
      </div>

      <section>
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-rose-600">
            Root causes
          </h2>
          <span className="mono rounded-full bg-rose-50 px-1.5 py-0.5 text-[9px] font-semibold text-rose-600">
            {rootCauses.length}
          </span>
          <span className="h-px flex-1 bg-slate-200" />
        </div>
        <div className="space-y-3">
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

      {collateral.length > 0 && (
        <section className="mt-8">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-600">
              Collateral
            </h2>
            <span className="mono rounded-full bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-600">
              {collateral.length}
            </span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>
          <p className="mb-3 text-[11px] text-slate-500">
            These will likely auto-recover once the root cause is fixed.
          </p>
          <div className="space-y-3">
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
      )}
    </div>
  )
}
