import {
  Activity,
  Gauge,
  LayoutDashboard,
  LogOut,
  Settings2,
  ShieldAlert,
  Waypoints,
} from 'lucide-react'
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom'

import AccountPage from '@/components/AccountPage'
import AdminPanel from '@/components/admin/AdminPanel'
import AdminRoute from '@/components/AdminRoute'
import DeviceDetailView from '@/components/DeviceDetailView'
import IncidentDetailView from '@/components/IncidentDetailView'
import IncidentView from '@/components/IncidentView'
import LoginPage from '@/components/LoginPage'
import MetricsView from '@/components/MetricsView'
import ProtectedRoute from '@/components/ProtectedRoute'
import StabilityView from '@/components/StabilityView'
import StaleDataBanner from '@/components/StaleDataBanner'
import TopologyView from '@/components/TopologyView'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'
import { useIncidents } from '@/hooks/useIncidents'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/', label: 'Topology', icon: LayoutDashboard, end: true },
  { to: '/metrics', label: 'Metrics', icon: Activity, end: false },
  { to: '/stability', label: 'Stability', icon: Gauge, end: false },
  { to: '/incidents', label: 'Incidents', icon: ShieldAlert, end: false },
] as const

function BrandMark() {
  return (
    <span className="relative flex h-8 w-8 items-center justify-center rounded-[9px] bg-slate-950 text-white shadow-sm">
      <Waypoints className="h-[17px] w-[17px]" strokeWidth={1.8} />
      <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-white bg-emerald-500" />
    </span>
  )
}

function AppHeader() {
  const { isAuthenticated, username, role, logout } = useAuth()
  const { incidents } = useIncidents()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navItems =
    role === 'admin'
      ? [
          ...NAV_ITEMS,
          { to: '/admin', label: 'Admin', icon: Settings2, end: false },
        ]
      : NAV_ITEMS

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/90 bg-white/85 backdrop-blur-xl">
      <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-5 px-4 sm:px-6">
        <Link
          to="/"
          className="flex shrink-0 items-center gap-2.5 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          aria-label="Network Analyser home"
        >
          <BrandMark />
          <span className="hidden flex-col sm:flex">
            <span className="text-[13px] font-semibold leading-none tracking-tight text-slate-950">
              Network Analyser
            </span>
            <span className="mt-1 text-[9px] font-medium uppercase leading-none tracking-[0.16em] text-slate-400">
              OT observability
            </span>
          </span>
        </Link>

        {isAuthenticated && (
          <nav
            aria-label="Primary navigation"
            className="-mx-1 flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto px-1 lg:ml-4"
          >
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      'group relative flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium transition-colors',
                      isActive
                        ? 'bg-slate-100 text-slate-950'
                        : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900',
                    )
                  }
                >
                  <Icon
                    className="h-3.5 w-3.5 opacity-70"
                    strokeWidth={1.9}
                  />
                  {item.label}
                  {item.label === 'Incidents' && incidents.length > 0 && (
                    <span
                      data-testid="incident-badge"
                      className="ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[9px] font-bold leading-none text-white"
                    >
                      {incidents.length}
                    </span>
                  )}
                </NavLink>
              )
            })}
          </nav>
        )}

        {isAuthenticated && (
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            <div className="mr-1 hidden items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-emerald-700 xl:flex">
              <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-emerald-500" />
              Live
            </div>
            <Link
              to="/account"
              className="group flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              title="Account settings"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-slate-100 text-[10px] font-semibold uppercase text-slate-700">
                {username?.slice(0, 2) ?? 'NA'}
              </span>
              <span className="hidden flex-col items-start md:flex">
                <span className="max-w-28 truncate text-[11px] font-semibold leading-none text-slate-800">
                  {username}
                </span>
                <span className="mt-1 text-[9px] uppercase leading-none tracking-[0.1em] text-slate-400">
                  {role}
                </span>
              </span>
            </Link>
            <span className="mx-1 hidden h-5 w-px bg-slate-200 sm:block" />
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="gap-1.5 text-slate-500 hover:text-rose-600"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Log out</span>
            </Button>
          </div>
        )}
      </div>
    </header>
  )
}

function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader />
      <StaleDataBanner />
      {/* relative: the topology page fills exactly what the header and the
          warning above leave of the window. */}
      <main className="relative flex-1">
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppLayout />}>
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <TopologyView />
            </ProtectedRoute>
          }
        />
        <Route
          path="/devices/:deviceId"
          element={
            <ProtectedRoute>
              <DeviceDetailView />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminPanel />
            </AdminRoute>
          }
        />
        <Route
          path="/account"
          element={
            <ProtectedRoute>
              <AccountPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/metrics"
          element={
            <ProtectedRoute>
              <MetricsView />
            </ProtectedRoute>
          }
        />
        <Route
          path="/stability"
          element={
            <ProtectedRoute>
              <StabilityView />
            </ProtectedRoute>
          }
        />
        <Route
          path="/incidents"
          element={
            <ProtectedRoute>
              <IncidentView />
            </ProtectedRoute>
          }
        />
        <Route
          path="/incidents/:incidentId"
          element={
            <ProtectedRoute>
              <IncidentDetailView />
            </ProtectedRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
