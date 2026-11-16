import { KeyRound, ShieldAlert, UserRound } from 'lucide-react'

import ChangePasswordForm from '@/components/admin/ChangePasswordForm'
import PageHeader from '@/components/ui/page-header'
import { Card } from '@/components/ui/card'
import { useAuth } from '@/contexts/AuthContext'

/**
 * Available to ANY authenticated user (admins and viewers alike) so viewers —
 * who have no /admin access — still have a way to rotate their seeded default
 * password. An account that still has its seeded password is sent here from
 * every other page (ProtectedRoute) until it has changed it.
 */
export default function AccountPage() {
  const { mustChangePassword, username, role } = useAuth()

  return (
    <div className="page-shell max-w-5xl">
      <PageHeader
        eyebrow={
          <span className="label-caps flex items-center gap-1.5">
            <UserRound className="h-3 w-3" /> Account
            <span className="h-1 w-1 rounded-full bg-slate-300" />
            Credentials
          </span>
        }
        title="Account"
        description="Manage your own credentials. No account can manage another user's password from here."
      />

      {mustChangePassword && (
        <div
          role="alert"
          data-testid="password-change-required"
          className="mb-5 flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-[12px] leading-relaxed text-amber-900"
        >
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <p>
            You are signed in with an initial password. Choose a new one to
            continue: nothing else is available until you have.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        <ChangePasswordForm />

        <Card className="h-fit overflow-hidden">
          <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
            <span className="flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-slate-100 text-[12px] font-semibold uppercase text-slate-600">
              {username?.slice(0, 2) ?? 'NA'}
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13px] font-semibold text-slate-900">
                {username}
              </p>
              <p className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.1em] text-slate-400">
                {role}
              </p>
            </div>
          </div>
          <div className="space-y-3 p-5">
            <div className="flex items-start gap-2.5">
              <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
              <p className="text-[11px] leading-relaxed text-slate-500">
                Passwords are hashed server-side and never stored in the
                browser. Your current session stays valid after a change.
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
              <p className="text-[9px] font-semibold uppercase tracking-[0.1em] text-slate-400">
                Session
              </p>
              <p className="mt-1 flex items-center gap-1.5 text-[11px] font-medium text-slate-700">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Authenticated
              </p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
