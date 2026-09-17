import { Outlet, Route, Routes } from 'react-router-dom'

import DeviceDetailView from '@/components/DeviceDetailView'
import TopologyView from '@/components/TopologyView'

function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex h-14 items-center border-b px-6">
        <h1 className="text-lg font-semibold tracking-tight">
          Network Analyser
        </h1>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<TopologyView />} />
        <Route path="/devices/:deviceId" element={<DeviceDetailView />} />
      </Route>
    </Routes>
  )
}
