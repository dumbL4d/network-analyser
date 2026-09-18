import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

import { API_BASE_URL, TOKEN_STORAGE_KEY, getStoredToken } from '@/lib/api'

interface AuthContextValue {
  token: string | null
  username: string | null
  role: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function loginRequest(
  username: string,
  password: string,
): Promise<{ access_token: string; role: string; username: string }> {
  const body = new URLSearchParams({ username, password })
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!response.ok) {
    throw new Error(
      response.status === 401
        ? 'Incorrect username or password'
        : `Login failed (HTTP ${response.status})`,
    )
  }
  return (await response.json()) as {
    access_token: string
    role: string
    username: string
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null)
  const [username, setUsername] = useState<string | null>(null)
  const [role, setRole] = useState<string | null>(null)
  // While true, the stored-token validation of the previous mount has not
  // finished; keeping the tree unmounted avoids a flash of the login page for
  // users whose session is actually still valid.
  const [isReady, setIsReady] = useState(false)

  // On mount, restore a previously stored token by validating it against
  // GET /api/auth/me. An expired/invalid token clears the stored session and
  // falls back to the login page silently (normal condition, not an error).
  useEffect(() => {
    let cancelled = false

    async function validate(): Promise<{
      username: string
      role: string
    } | null> {
      const stored = getStoredToken()
      if (stored === null) return null

      const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${stored}` },
      })
      if (!response.ok) throw new Error('Session invalid')
      return (await response.json()) as { username: string; role: string }
    }

    validate()
      .then((me) => {
        if (cancelled || me === null) return
        setToken(getStoredToken())
        setUsername(me.username)
        setRole(me.role)
      })
      .catch(() => {
        if (cancelled) return
        localStorage.removeItem(TOKEN_STORAGE_KEY)
      })
      .finally(() => {
        if (!cancelled) setIsReady(true)
      })

    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const data = await loginRequest(username, password)
    localStorage.setItem(TOKEN_STORAGE_KEY, data.access_token)
    setToken(data.access_token)
    setUsername(data.username)
    setRole(data.role)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setToken(null)
    setUsername(null)
    setRole(null)
  }, [])

  if (!isReady) {
    return null
  }

  return (
    <AuthContext.Provider
      value={{
        token,
        username,
        role,
        login,
        logout,
        isAuthenticated: token !== null,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === null) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}