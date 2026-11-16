import { Plus, ShieldCheck, Trash2, UserRound } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import ChangePasswordForm from '@/components/admin/ChangePasswordForm'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { useAuth } from '@/contexts/AuthContext'
import { createUser, deleteUser, fetchUsers } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { UserOut, UserRole } from '@/types/user'

interface UserFormState {
  username: string
  password: string
  role: UserRole
}

const EMPTY_USER_FORM: UserFormState = {
  username: '',
  password: '',
  role: 'viewer',
}

function RoleBadge({ role }: { role: UserRole }) {
  const admin = role === 'admin'
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]',
        admin
          ? 'border-violet-200 bg-violet-50 text-violet-700'
          : 'border-slate-200 bg-slate-50 text-slate-600',
      )}
    >
      {admin ? (
        <ShieldCheck className="h-2.5 w-2.5" />
      ) : (
        <UserRound className="h-2.5 w-2.5" />
      )}
      {role}
    </span>
  )
}

export default function AdminUsersTab() {
  const { username: myUsername } = useAuth()

  const [users, setUsers] = useState<UserOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [form, setForm] = useState<UserFormState>(EMPTY_USER_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<UserOut | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const loadUsers = useCallback(async () => {
    // loading starts true on mount (so no sync setState in the effect);
    // CRUD-triggered refreshes run from event handlers after transition.
    try {
      setUsers(await fetchUsers())
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchUsers()
      .then((data) => {
        if (!cancelled) setUsers(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setDialogError(null)
    try {
      await createUser(form)
      setDialogOpen(false)
      setForm(EMPTY_USER_FORM)
      await loadUsers()
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async () => {
    if (deleteTarget === null) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteUser(deleteTarget.id)
      setDeleteTarget(null)
      await loadUsers()
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-[13px] font-semibold text-slate-900">
              User accounts
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Admins manage the network; viewers have read-only access.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="mono rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-500">
              {users.length} {users.length === 1 ? 'user' : 'users'}
            </span>
            <Button
              size="sm"
              onClick={() => {
                setForm(EMPTY_USER_FORM)
                setDialogError(null)
                setDialogOpen(true)
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              Add User
            </Button>
          </div>
        </div>

        {loadError !== null && (
          <p className="border-b border-rose-100 bg-rose-50/60 px-5 py-2.5 text-[12px] text-rose-700">
            Failed to load users: {loadError}
          </p>
        )}

        <Table className="table-density">
          <TableHeader>
            <TableRow>
              <TableHead>Username</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={3}
                  className="py-10 text-center text-[12px] text-slate-500"
                >
                  Loading users…
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-100 text-[10px] font-semibold uppercase text-slate-600">
                        {user.username.slice(0, 2)}
                      </span>
                      <span className="text-[12px] font-medium text-slate-800">
                        {user.username}
                      </span>
                      {user.username === myUsername && (
                        <span className="rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em] text-blue-700">
                          you
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <RoleBadge role={user.role as UserRole} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                      onClick={() => {
                        setDeleteTarget(user)
                        setDeleteError(null)
                      }}
                    >
                      <Trash2 className="h-3 w-3" />
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add User</DialogTitle>
            <DialogDescription>
              Create a new login. The password is hashed server-side.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="nu-username">Username</Label>
              <Input
                id="nu-username"
                value={form.username}
                onChange={(e) =>
                  setForm({ ...form, username: e.target.value })
                }
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="nu-password">Password (min 8 chars)</Label>
              <Input
                id="nu-password"
                type="password"
                value={form.password}
                onChange={(e) =>
                  setForm({ ...form, password: e.target.value })
                }
                required
              />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select
                value={form.role}
                onValueChange={(v) =>
                  setForm({ ...form, role: v as UserRole })
                }
              >
                <SelectTrigger data-testid="nu-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">viewer</SelectItem>
                  <SelectItem value="admin">admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {dialogError !== null && (
              <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
                {dialogError}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialogOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Creating…' : 'Create user'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete user {deleteTarget?.username}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes {deleteTarget?.username}&apos;s account
              and can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError !== null && (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              {deleteError}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault()
                handleDelete()
              }}
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ChangePasswordForm />
    </div>
  )
}
