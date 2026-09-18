import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import ProtectedRoute from '@/components/ProtectedRoute'
import { useAuth } from '@/contexts/AuthContext'

/**
 * Admin-only route guard. Composed on top of ProtectedRoute (so auth is checked
 * once, not duplicated) plus a role check that redirects viewers away even if
 * they navigate directly to the URL.
 */
export default function AdminRoute({ children }: { children: ReactNode }) {
  const { role } = useAuth()

  return (
    <ProtectedRoute>
      {role === 'admin' ? <>{children}</> : <Navigate to="/" replace />}
    </ProtectedRoute>
  )
}