import { Card, CardContent } from '@/components/ui/card'
import { useIncidentStats } from '@/hooks/useIncidentRecords'
import { formatDuration } from '@/lib/format'

function StatCard({
  testId,
  label,
  value,
  hint,
}: {
  testId: string
  label: string
  value: string
  hint: string
}) {
  return (
    <Card data-testid={testId}>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}

/** Summary cards above the Incidents tabs, from GET /api/stats/incidents. */
export default function IncidentSummary() {
  const { data: stats, error } = useIncidentStats()

  if (error !== null && stats === null) {
    return (
      <p className="mb-6 text-sm text-red-600">
        Failed to load incident statistics: {error}
      </p>
    )
  }

  return (
    <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard
        testId="stat-incidents"
        label="Incidents"
        value={stats ? String(stats.count) : '—'}
        hint={stats ? `${stats.open_count} not yet resolved` : 'all recorded'}
      />
      <StatCard
        testId="stat-detection"
        label="Mean detection delay"
        value={formatDuration(stats?.mean_detection_delay_seconds)}
        hint="first failing probe to incident raised"
      />
      <StatCard
        testId="stat-mttr"
        label="MTTR"
        value={formatDuration(stats?.mttr_seconds)}
        hint="incident raised to resolved, on average"
      />
      <StatCard
        testId="stat-suppressed"
        label="Alerts suppressed"
        value={stats ? String(stats.alerts_suppressed) : '—'}
        hint="collateral devices with no incident of their own"
      />
    </div>
  )
}
