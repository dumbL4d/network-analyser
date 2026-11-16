/** Mirrors the backend user-management schemas. */
export type UserRole = 'admin' | 'viewer'

export interface UserOut {
  id: number
  username: string
  role: string
}

/** POST /api/users body (backend UserCreate). */
export interface UserCreate {
  username: string
  password: string
  role: UserRole
}

/** PATCH /api/auth/change-password body (backend PasswordChangeRequest). */
export interface PasswordChangeRequest {
  current_password: string
  new_password: string
}