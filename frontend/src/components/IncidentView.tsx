import { Radar, ShieldAlert } from 'lucide-react'

import ActiveIncidents from '@/components/incidents/ActiveIncidents'
import IncidentHistory from '@/components/incidents/IncidentHistory'
import IncidentSummary from '@/components/incidents/IncidentSummary'
import PageHeader from '@/components/ui/page-header'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIncidents } from '@/hooks/useIncidents'

/**
 * The Incidents page: summary cards, then two tabs.
 *
 * - Active: what is wrong right now (the live root-cause / collateral set).
 * - History: every incident the backend has recorded, with its timeline.
 */
export default function IncidentView() {
  const { incidents } = useIncidents()
  const activeCount = incidents.length

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow={
          <span className="label-caps flex items-center gap-1.5">
            <ShieldAlert className="h-3 w-3" /> Incident response
            <span className="h-1 w-1 rounded-full bg-slate-300" />
            Root-cause analysis
          </span>
        }
        title="Incidents"
        description="One outage, one incident. Collateral alerts are grouped under the device that actually failed."
        actions={
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-medium text-slate-500 shadow-card">
              <Radar className="h-3.5 w-3.5 text-blue-500" />
              Live detection
            </span>
            <span
              className={
                activeCount > 0
                  ? 'inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[10px] font-semibold text-rose-700 shadow-card'
                  : 'inline-flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[10px] font-semibold text-emerald-700 shadow-card'
              }
            >
              <span
                className={
                  activeCount > 0
                    ? 'h-1.5 w-1.5 rounded-full bg-rose-500'
                    : 'h-1.5 w-1.5 rounded-full bg-emerald-500'
                }
              />
              {activeCount > 0
                ? `${activeCount} active`
                : 'All clear'}
            </span>
          </div>
        }
      />

      <IncidentSummary />

      <Tabs defaultValue="active" className="mt-6">
        <TabsList className="mb-5">
          <TabsTrigger value="active" data-testid="active-tab">
            Active
          </TabsTrigger>
          <TabsTrigger value="history" data-testid="history-tab">
            History
          </TabsTrigger>
        </TabsList>
        <TabsContent value="active">
          <ActiveIncidents />
        </TabsContent>
        <TabsContent value="history">
          <IncidentHistory />
        </TabsContent>
      </Tabs>
    </div>
  )
}
