import { KeyRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/contexts/AuthContext'
import { changePassword } from '@/lib/api'

/**
 * Self-service "change my own password" form. Reused by the admin Users tab
 * and the /account page (which viewers can reach) so every authenticated user
 * can rotate their seeded default password.
 */
export default function ChangePasswordForm() {
  const { passwordChanged } = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setSuccess(null)
    setError(null)
    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword('')
      setNewPassword('')
      passwordChanged() // a seeded password is gone: the rest of the app opens
      setSuccess('Password updated successfully')
      // Auto-clear the success note so a later failure isn't shown alongside a
      // stale success (no toast dependency needed for MVP).
      window.setTimeout(() => setSuccess(null), 4000)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
          <KeyRound className="h-3.5 w-3.5" />
        </span>
        <div>
          <p className="text-[13px] font-semibold text-slate-900">
            Change My Password
          </p>
          <p className="mt-0.5 max-w-2xl text-[11px] leading-relaxed text-slate-500">
            Rotate your own password. Your current session stays valid until
            its natural expiry; only future logins require the new password.
          </p>
        </div>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
        </div>
        {success !== null && (
          <p className="text-[12px] font-medium text-emerald-700">{success}</p>
        )}
        {error !== null && (
          <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
            {error}
          </p>
        )}
        <Button type="submit" disabled={submitting}>
          {submitting ? 'Updating…' : 'Update password'}
        </Button>
      </form>
    </Card>
  )
}
