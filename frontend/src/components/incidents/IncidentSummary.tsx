import {
  BellOff,
  Clock3,
  ShieldAlert,
  Timer,
  Wrench,
} from 'lucide-react'

import KpiCard from '@/components/ui/kpi-card'
import { useIncidentStats } from '@/hooks/useIncidentRecords'
import { formatDuration } from '@/lib/format'
import { Card } from '@/components/ui/card'

/** Summary cards above the Incidents tabs, from GET /api/stats/incidents. */
export default function IncidentSummary() {
  const { data: stats, error } = useIncidentStats()

  if (error !== null && stats === null) {
    return (
      <Card className="mb-6 border-rose-200 p-4 text-[12px] text-rose-700">
        Failed to load incident statistics: {error}
      </Card>
    )
  }

  return (
    <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <KpiCard
        testId="stat-incidents"
        label="Incidents"
        value={stats ? String(stats.count) : '—'}
        hint={
          stats
            ? `${stats.open_count} open · ${stats.resolved_count} resolved`
            : 'All recorded incidents'
        }
        icon={ShieldAlert}
        tone={stats && stats.open_count > 0 ? 'rose' : 'neutral'}
      />
      <KpiCard
        testId="stat-detection"
        label="Mean detection delay"
        value={formatDuration(stats?.mean_detection_delay_seconds)}
        hint="First failing probe to incident raised"
        icon={Timer}
        tone="amber"
      />
      <KpiCard
        testId="stat-mttr"
        label="MTTR"
        value={formatDuration(stats?.mttr_seconds)}
        hint="Incident raised to resolved, on average"
        icon={Wrench}
        tone="blue"
      />
      <KpiCard
        testId="stat-suppressed"
        label="Alerts suppressed"
        value={stats ? String(stats.alerts_suppressed) : '—'}
        hint="Collateral devices rolled into one incident"
        icon={BellOff}
        tone="violet"
        footer={
          <div className="mt-3 flex items-center gap-1.5 border-t border-slate-100 pt-2 text-[9px] font-medium uppercase tracking-[0.08em] text-slate-400">
            <Clock3 className="h-3 w-3" />
            Root-cause noise reduction
          </div>
        }
      />
    </div>
  )
}
