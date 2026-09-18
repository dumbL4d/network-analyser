import { Link, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'

import AccountPage from '@/components/AccountPage'
import AdminPanel from '@/components/admin/AdminPanel'
import AdminRoute from '@/components/AdminRoute'
import DeviceDetailView from '@/components/DeviceDetailView'
import IncidentView from '@/components/IncidentView'
import LoginPage from '@/components/LoginPage'
import MetricsView from '@/components/MetricsView'
import ProtectedRoute from '@/components/ProtectedRoute'
import StabilityView from '@/components/StabilityView'
import TopologyView from '@/components/TopologyView'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'
import { useIncidents } from '@/hooks/useIncidents'

function AppHeader() {
  const { isAuthenticated, username, role, logout } = useAuth()
  const { incidents } = useIncidents()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <div className="flex items-center gap-6">
        <h1 className="text-lg font-semibold tracking-tight">Network Analyser</h1>
        {isAuthenticated && (
          <nav className="flex items-center gap-1">
            <Link
              to="/metrics"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Metrics
            </Link>
            <Link
              to="/stability"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Stability
            </Link>
            <Link
              to="/incidents"
              className="flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Incidents
              {isAuthenticated && incidents.length > 0 && (
                <span
                  data-testid="incident-badge"
                  className="animate-pulse rounded-full bg-red-500 px-2 py-0.5 text-xs font-semibold text-white"
                >
                  {incidents.length}
                </span>
              )}
            </Link>
            {role === 'admin' && (
              <Link
                to="/admin"
                className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                Admin
              </Link>
            )}
          </nav>
        )}
      </div>
      {isAuthenticated && (
        <div className="flex items-center gap-3">
          <Link
            to="/account"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Change Password
          </Link>
          <span className="text-sm text-muted-foreground">
            {username}{' '}
            <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium">
              {role}
            </span>
          </span>
          <Button variant="outline" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      )}
    </header>
  )
}

function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader />
      <main className="flex-1">
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
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}