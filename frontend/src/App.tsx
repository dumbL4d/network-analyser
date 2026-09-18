import { Link, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'

import AccountPage from '@/components/AccountPage'
import AdminPanel from '@/components/admin/AdminPanel'
import AdminRoute from '@/components/AdminRoute'
import DeviceDetailView from '@/components/DeviceDetailView'
import LoginPage from '@/components/LoginPage'
import ProtectedRoute from '@/components/ProtectedRoute'
import TopologyView from '@/components/TopologyView'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/contexts/AuthContext'

function AppHeader() {
  const { isAuthenticated, username, role, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="flex h-14 items-center justify-between border-b px-6">
      <div className="flex items-center gap-6">
        <h1 className="text-lg font-semibold tracking-tight">Network Analyser</h1>
        {isAuthenticated && role === 'admin' && (
          <nav className="flex items-center gap-1">
            <Link
              to="/admin"
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Admin
            </Link>
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
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}