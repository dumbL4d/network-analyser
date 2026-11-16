import ActiveIncidents from '@/components/incidents/ActiveIncidents'
import IncidentHistory from '@/components/incidents/IncidentHistory'
import IncidentSummary from '@/components/incidents/IncidentSummary'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

/**
 * The Incidents page: summary cards, then two tabs.
 *
 * - Active: what is wrong right now (the live root-cause / collateral set).
 * - History: every incident the backend has recorded, with its timeline.
 */
export default function IncidentView() {
  return (
    <div className="p-8">
      <h1 className="mb-4 text-xl font-semibold">Incidents</h1>

      <IncidentSummary />

      <Tabs defaultValue="active">
        <TabsList>
          <TabsTrigger value="active" data-testid="active-tab">
            Active
          </TabsTrigger>
          <TabsTrigger value="history" data-testid="history-tab">
            History
          </TabsTrigger>
        </TabsList>
        <TabsContent value="active" className="pt-2">
          <ActiveIncidents />
        </TabsContent>
        <TabsContent value="history" className="pt-2">
          <IncidentHistory />
        </TabsContent>
      </Tabs>
    </div>
  )
}
