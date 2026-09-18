import ChangePasswordForm from '@/components/admin/ChangePasswordForm'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'

/**
 * Available to ANY authenticated user (admins and viewers alike) so viewers —
 * who have no /admin access — still have a way to rotate their seeded default
 * password.
 */
export default function AccountPage() {
  return (
    <div className="mx-auto max-w-md p-6">
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