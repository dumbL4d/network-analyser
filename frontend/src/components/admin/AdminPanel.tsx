import AdminChaosTab from '@/components/admin/AdminChaosTab'
import AdminDevicesTab from '@/components/admin/AdminDevicesTab'
import AdminLinksTab from '@/components/admin/AdminLinksTab'
import AdminSettingsTab from '@/components/admin/AdminSettingsTab'
import AdminUsersTab from '@/components/admin/AdminUsersTab'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

/**
 * Phase 4 Admin Panel: admin-only device CRUD, the extra links between
 * devices, live monitoring settings, and user management, plus the
 * password-change form (in the Users tab).
 */
export default function AdminPanel() {
  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-4">
        <h2 className="text-2xl font-semibold tracking-tight">Admin Panel</h2>
        <p className="text-sm text-muted-foreground">
          Manage devices, links, monitoring settings, and users, and inject
          faults into the simulated network.
        </p>
      </div>
      <Tabs defaultValue="devices">
        <TabsList>
          <TabsTrigger value="devices">Devices</TabsTrigger>
          <TabsTrigger value="links" data-testid="links-tab">
            Links
          </TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="chaos" data-testid="chaos-tab">
            Chaos
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
      </Tabs>
    </div>
  )
}