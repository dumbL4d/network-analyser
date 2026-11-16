import { Settings2 } from 'lucide-react'

import AdminAuditTab from '@/components/admin/AdminAuditTab'
import AdminChaosTab from '@/components/admin/AdminChaosTab'
import AdminDevicesTab from '@/components/admin/AdminDevicesTab'
import AdminLinksTab from '@/components/admin/AdminLinksTab'
import AdminSettingsTab from '@/components/admin/AdminSettingsTab'
import AdminUsersTab from '@/components/admin/AdminUsersTab'
import PageHeader from '@/components/ui/page-header'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

/**
 * Admin Panel: admin-only device CRUD, the extra links between
 * devices, live monitoring settings, and user management, plus the
 * password-change form (in the Users tab), fault injection and the audit log.
 */
export default function AdminPanel() {
  return (
    <div className="page-shell">
      <PageHeader
        eyebrow={
          <span className="label-caps flex items-center gap-1.5">
            <Settings2 className="h-3 w-3" /> Administration
            <span className="h-1 w-1 rounded-full bg-slate-300" />
            Admin only
          </span>
        }
        title="Admin Panel"
        description="Manage devices, links, monitoring settings, and users, inject faults into the simulated network, and see who did what."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-medium text-slate-500 shadow-card">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-500" />
            Changes apply live
          </span>
        }
      />
      <Tabs defaultValue="devices">
        <TabsList className="mb-5 flex-wrap">
          <TabsTrigger value="devices">Devices</TabsTrigger>
          <TabsTrigger value="links" data-testid="links-tab">
            Links
          </TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="chaos" data-testid="chaos-tab">
            Chaos
          </TabsTrigger>
          <TabsTrigger value="audit" data-testid="audit-tab">
            Audit
          </TabsTrigger>
        </TabsList>
        <TabsContent value="devices">
          <AdminDevicesTab />
        </TabsContent>
        <TabsContent value="links">
          <AdminLinksTab />
        </TabsContent>
        <TabsContent value="settings">
          <AdminSettingsTab />
        </TabsContent>
        <TabsContent value="users">
          <AdminUsersTab />
        </TabsContent>
        <TabsContent value="chaos">
          <AdminChaosTab />
        </TabsContent>
        <TabsContent value="audit">
          <AdminAuditTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
