import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
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
import { Textarea } from '@/components/ui/textarea'
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
import {
  createDevice,
  deleteDevice,
  fetchDevices,
  updateDevice,
} from '@/lib/api'
import type { DeviceOut, DeviceType } from '@/types/device'
import { DEVICE_TYPES } from '@/types/device'

interface DeviceFormState {
  id: string
  name: string
  type: DeviceType
  ip: string
  zone: string
  parentId: string // '' means "None (root)"
  pingPort: string
  notes: string
}

const EMPTY_FORM: DeviceFormState = {
  id: '',
  name: '',
  type: 'switch',
  ip: '',
  zone: '',
  parentId: '',
  pingPort: '80',
  notes: '',
}

function DeviceForm({
  form,
  setForm,
  devices,
  editing,
}: {
  form: DeviceFormState
  setForm: (next: DeviceFormState) => void
  devices: DeviceOut[]
  editing: boolean
}) {
  return (
    <div className="grid gap-4 py-2">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="dd-id">ID</Label>
          <Input
            id="dd-id"
            value={form.id}
            onChange={(e) => setForm({ ...form, id: e.target.value })}
            disabled={editing}
            placeholder="kebab-case-id"
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="dd-name">Name</Label>
          <Input
            id="dd-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Display name"
            required
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Type</Label>
          <Select
            value={form.type}
            onValueChange={(v) => setForm({ ...form, type: v as DeviceType })}
          >
            <SelectTrigger data-testid="dd-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DEVICE_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="dd-ip">IP</Label>
          <Input
            id="dd-ip"
            value={form.ip}
            onChange={(e) => setForm({ ...form, ip: e.target.value })}
            placeholder="10.99.0.x"
            required
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="dd-zone">Zone</Label>
          <Input
            id="dd-zone"
            value={form.zone}
            onChange={(e) => setForm({ ...form, zone: e.target.value })}
            placeholder="ot-tier"
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="dd-port">Ping port</Label>
          <Input
            id="dd-port"
            type="number"
            min={1}
            max={65535}
            value={form.pingPort}
            onChange={(e) => setForm({ ...form, pingPort: e.target.value })}
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label>Parent device</Label>
        <Select
          value={form.parentId === '' ? 'none' : form.parentId}
          onValueChange={(v) =>
            setForm({ ...form, parentId: v === 'none' ? '' : v })
          }
        >
          <SelectTrigger data-testid="dd-parent">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">None (root)</SelectItem>
            {devices
              .filter((d) => d.id !== form.id)
              .map((d) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.id} ({d.name})
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        {editing && (
          <p className="text-xs text-muted-foreground">
            Backend PATCH ignores a null parent, so a parent can only be
            re-assigned to another device here, not removed.
          </p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor="dd-notes">Notes</Label>
        <Textarea
          id="dd-notes"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
          rows={2}
          placeholder="Optional notes"
        />
      </div>
    </div>
  )
}

export default function AdminDevicesTab() {
  const [devices, setDevices] = useState<DeviceOut[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingDevice, setEditingDevice] = useState<DeviceOut | null>(null)
  const [form, setForm] = useState<DeviceFormState>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)

  const [deleteTarget, setDeleteTarget] = useState<DeviceOut | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const loadDevices = useCallback(async () => {
    // loading starts true on mount (so no sync setState in the effect);
    // CRUD-triggered refreshes run from event handlers after transition.
    try {
      setDevices(await fetchDevices())
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchDevices()
      .then((data) => {
        if (!cancelled) setDevices(data)
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

  const openAddDialog = () => {
    setEditingDevice(null)
    setForm(EMPTY_FORM)
    setDialogError(null)
    setDialogOpen(true)
  }

  const openEditDialog = (device: DeviceOut) => {
    setEditingDevice(device)
    setForm({
      id: device.id,
      name: device.name,
      type: device.type as DeviceType,
      ip: device.ip,
      zone: device.zone,
      parentId: device.parent_id ?? '',
      pingPort: String(device.ping_port),
      notes: device.notes,
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (editingDevice !== null) {
      // id is immutable (mirrors the backend); parent_id is only sent when the
      // user picked an actual device ('' is "None", which the backend ignores).
      const patch: Parameters<typeof updateDevice>[1] = {
        name: form.name,
        type: form.type,
        ip: form.ip,
        zone: form.zone,
        ping_port: Number(form.pingPort),
        notes: form.notes,
      }
      if (form.parentId !== '' && form.parentId !== editingDevice.parent_id) {
        patch.parent_id = form.parentId
      }
      setSubmitting(true)
      setDialogError(null)
      try {
        await updateDevice(editingDevice.id, patch)
        setDialogOpen(false)
        await loadDevices()
      } catch (err) {
        setDialogError(err instanceof Error ? err.message : String(err))
      } finally {
        setSubmitting(false)
      }
    } else {
      setSubmitting(true)
      setDialogError(null)
      try {
        await createDevice({
          id: form.id,
          name: form.name,
          type: form.type,
          ip: form.ip,
          zone: form.zone,
          parent_id: form.parentId === '' ? null : form.parentId,
          ping_port: Number(form.pingPort),
          notes: form.notes,
        })
        setDialogOpen(false)
        await loadDevices()
      } catch (err) {
        setDialogError(err instanceof Error ? err.message : String(err))
      } finally {
        setSubmitting(false)
      }
    }
  }

  const handleDelete = async () => {
    if (deleteTarget === null) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteDevice(deleteTarget.id)
      setDeleteTarget(null)
      await loadDevices()
    } catch (err) {
      // Keep the dialog open so the backend's message (e.g. the 409 child-rule
      // rejection) is visible instead of the dialog silently closing.
      setDeleteError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {devices.length} devices
        </p>
        <Button onClick={openAddDialog}>Add Device</Button>
      </div>

      {loadError !== null && (
        <p className="text-sm text-red-600">Failed to load devices: {loadError}</p>
      )}

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Zone</TableHead>
              <TableHead>IP</TableHead>
              <TableHead>Parent</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  Loading devices…
                </TableCell>
              </TableRow>
            ) : (
              devices.map((device) => (
                <TableRow key={device.id}>
                  <TableCell className="font-mono text-xs">{device.id}</TableCell>
                  <TableCell>{device.name}</TableCell>
                  <TableCell>{device.type}</TableCell>
                  <TableCell>{device.zone}</TableCell>
                  <TableCell className="font-mono text-xs">{device.ip}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {device.parent_id ?? '—'}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openEditDialog(device)}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => {
                          setDeleteTarget(device)
                          setDeleteError(null)
                        }}
                      >
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingDevice !== null ? `Edit ${editingDevice.id}` : 'Add Device'}
            </DialogTitle>
            <DialogDescription>
              {editingDevice !== null
                ? 'Update device details. The ID is immutable.'
                : 'Register a new device in the monitored network.'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <DeviceForm form={form} setForm={setForm} devices={devices} editing={editingDevice !== null} />
            {dialogError !== null && (
              <p className="text-sm text-red-600">{dialogError}</p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting
                  ? 'Saving…'
                  : editingDevice !== null
                    ? 'Save changes'
                    : 'Create device'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleteTarget?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete {deleteTarget?.id}? This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError !== null && (
            <p className="text-sm text-red-600">{deleteError}</p>
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
    </div>
  )
}