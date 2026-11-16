import ChangePasswordForm from '@/components/admin/ChangePasswordForm'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useAuth } from '@/contexts/AuthContext'

/**
 * Available to ANY authenticated user (admins and viewers alike) so viewers —
 * who have no /admin access — still have a way to rotate their seeded default
 * password. An account that still has its seeded password is sent here from
 * every other page (ProtectedRoute) until it has changed it.
 */
export default function AccountPage() {
  const { mustChangePassword } = useAuth()

  return (
    <div className="mx-auto max-w-md p-6">
      {mustChangePassword && (
        <p
          role="alert"
          data-testid="password-change-required"
          className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
        >
          You are signed in with an initial password. Choose a new one to
          continue: nothing else is available until you have.
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>
            Manage your own credentials. No account can manage another user's
            password from here.
          </CardDescription>
        </CardHeader>
        <CardContent className="border-t pt-4">
          <ChangePasswordForm />
        </CardContent>
      </Card>
    </div>
  )
}