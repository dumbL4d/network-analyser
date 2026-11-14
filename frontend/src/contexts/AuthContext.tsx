import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'

import {
  API_BASE_URL,
  PASSWORD_CHANGE_REQUIRED_EVENT,
  SESSION_EXPIRED_EVENT,
  TOKEN_STORAGE_KEY,
  getStoredToken,
} from '@/lib/api'

interface AuthContextValue {
  token: string | null
  username: string | null
  role: string | null
  /**
   * True while the account still has a seeded password. Until it is changed
   * the backend answers 403 to everything else, so the only page to show is
   * the account page.
   */
  mustChangePassword: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  /** Call after a successful password change: the account is unlocked. */
  passwordChanged: () => void
  isAuthenticated: boolean
}

interface Me {
  username: string
  role: string
  must_change_password: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function loginRequest(
  username: string,
  password: string,
): Promise<Me & { access_token: string }> {
  const body = new URLSearchParams({ username, password })
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Incorrect username or password')
    }
    // 429: too many wrong passwords. The backend says how long to wait.
    const detail: unknown = await response
      .json()
      .then((error: { detail?: unknown }) => error.detail)
      .catch(() => null)
    throw new Error(
      typeof detail === 'string'
        ? detail
        : `Login failed (HTTP ${response.status})`,
    )
  }
  return (await response.json()) as Me & { access_token: string }
}

/** Who the stored token belongs to. Rejects when it is no longer valid. */
async function fetchMe(): Promise<Me> {
  const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
    headers: { Authorization: `Bearer ${getStoredToken()}` },
  })
  if (!response.ok) throw new Error('Session invalid')
  return (await response.json()) as Me
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null)
  const [username, setUsername] = useState<string | null>(null)
  const [role, setRole] = useState<string | null>(null)
  const [mustChangePassword, setMustChangePassword] = useState(false)
  // While true, the stored-token validation of the previous mount has not
  // finished; keeping the tree unmounted avoids a flash of the login page for
  // users whose session is actually still valid.
  const [isReady, setIsReady] = useState(false)

  // On mount, restore a previously stored token by validating it against
  // GET /api/auth/me. An expired/invalid token clears the stored session and
  // falls back to the login page silently (normal condition, not an error).
  useEffect(() => {
    let cancelled = false

    const validate = (): Promise<Me | null> =>
      getStoredToken() === null ? Promise.resolve(null) : fetchMe()

    validate()
      .then((me) => {
        if (cancelled || me === null) return
        setToken(getStoredToken())
        setUsername(me.username)
        setRole(me.role)
        setMustChangePassword(me.must_change_password)
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
    setMustChangePassword(data.must_change_password)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setToken(null)
    setUsername(null)
    setRole(null)
    setMustChangePassword(false)
  }, [])

  const passwordChanged = useCallback(() => setMustChangePassword(false), [])

  // What the backend says about the session as a whole (see lib/api.ts).
  useEffect(() => {
    // The token expired or the account is gone: back to the login page.
    const onExpired = () => logout()
    // Ask instead of assuming: the 403 may be the late answer to a request
    // that was sent just before the password was changed.
    const onPasswordChangeRequired = () => {
      if (mustChangePassword) return
      fetchMe()
        .then((me) => setMustChangePassword(me.must_change_password))
        .catch(() => {})
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired)
    window.addEventListener(
      PASSWORD_CHANGE_REQUIRED_EVENT,
      onPasswordChangeRequired,
    )
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired)
      window.removeEventListener(
        PASSWORD_CHANGE_REQUIRED_EVENT,
        onPasswordChangeRequired,
      )
    }
  }, [logout, mustChangePassword])

  if (!isReady) {
    return null
  }

  return (
    <AuthContext.Provider
      value={{
        token,
        username,
        role,
        mustChangePassword,
        login,
        logout,
        passwordChanged,
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