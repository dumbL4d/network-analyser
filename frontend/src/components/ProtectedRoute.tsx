import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '@/contexts/AuthContext'

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, mustChangePassword } = useAuth()
  const { pathname } = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  // A seeded password has to be replaced first. Until then the backend answers
  // 403 to everything else, so every page leads to the account page.
  if (mustChangePassword && pathname !== '/account') {
    return <Navigate to="/account" replace />
  }

  return <>{children}</>
}
