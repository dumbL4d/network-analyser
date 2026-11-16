import { Link2, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
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
import { createLink, deleteLink, fetchDevices, fetchLinks } from '@/lib/api'
import type { DeviceOut } from '@/types/device'
import type { LinkOut } from '@/types/topology'

function DeviceSelect({
  id,
  testId,
  value,
  devices,
  onChange,
}: {
  id: string
  testId: string
  value: string
  devices: DeviceOut[]
  onChange: (deviceId: string) => void
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} data-testid={testId} className="w-[220px]">
        <SelectValue placeholder="Select a device" />
      </SelectTrigger>
      <SelectContent>
        {devices.map((device) => (
          <SelectItem key={device.id} value={device.id}>
            {device.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/**
 * Admin tab for the extra links between devices: a second uplink, a ring.
 * They are in addition to each device's parent, and are what makes the
 * topology redundant. The backend validates a new link, and its message is
 * shown as it is.
 */
export default function AdminLinksTab() {
  const [devices, setDevices] = useState<DeviceOut[]>([])
  const [links, setLinks] = useState<LinkOut[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deviceA, setDeviceA] = useState('')
  const [deviceB, setDeviceB] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // The links again, after an action changed them.
  const reloadLinks = useCallback(async () => {
    setLinks(await fetchLinks())
  }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([fetchDevices(), fetchLinks()])
      .then(([loadedDevices, loadedLinks]) => {
        if (cancelled) return
        setDevices(loadedDevices)
        setLinks(loadedLinks)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId

  // Run an admin action; on failure show what the backend said.
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      await reloadLinks()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const handleAdd = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(async () => {
      await createLink(deviceA, deviceB)
      setDeviceA('')
      setDeviceB('')
    })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5 rounded-xl border border-blue-200 bg-blue-50/60 px-3.5 py-3">
        <Link2 className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
        <p className="text-[11px] leading-relaxed text-blue-800">
          {links.length} extra {links.length === 1 ? 'link' : 'links'}, in
          addition to each device&apos;s parent. A link gives a device a second
          way to the rest of the network.
        </p>
      </div>

      {loadError !== null && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          Failed to load links: {loadError}
        </p>
      )}

      <Card className="overflow-hidden">
        <div className="border-b border-slate-100 px-5 py-4">
          <p className="text-[13px] font-semibold text-slate-900">
            Add redundant link
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            Create a second path between two devices to make the topology
            tolerant of a single failure.
          </p>
        </div>
        <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-3 px-5 py-4">
          <div className="space-y-1.5">
            <Label htmlFor="link-device-a">Device</Label>
            <DeviceSelect
              id="link-device-a"
              testId="link-device-a"
              value={deviceA}
              devices={devices}
              onChange={setDeviceA}
            />
          </div>
          <span className="mb-2 hidden text-[11px] font-medium text-slate-400 sm:inline">
            ↔
          </span>
          <div className="space-y-1.5">
            <Label htmlFor="link-device-b">Linked to</Label>
            <DeviceSelect
              id="link-device-b"
              testId="link-device-b"
              value={deviceB}
              devices={devices}
              onChange={setDeviceB}
            />
          </div>
          <Button
            type="submit"
            data-testid="link-add"
            disabled={busy || deviceA === '' || deviceB === ''}
          >
            <Plus className="h-3.5 w-3.5" />
            Add link
          </Button>
        </form>
        {actionError !== null && (
          <p
            data-testid="link-error"
            className="border-t border-rose-100 bg-rose-50/60 px-5 py-2.5 text-[12px] text-rose-700"
          >
            {actionError}
          </p>
        )}
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <p className="text-[13px] font-semibold text-slate-900">
              Extra links
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Redundant paths beyond the parent-child tree.
            </p>
          </div>
          <span className="mono rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-medium text-slate-500">
            {links.length}
          </span>
        </div>
        <Table className="table-density">
          <TableHeader>
            <TableRow>
              <TableHead>Device</TableHead>
              <TableHead>Linked to</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {links.length === 0 ? (
              <TableRow data-testid="links-empty">
                <TableCell
                  colSpan={3}
                  className="py-10 text-center text-[12px] text-slate-500"
                >
                  No extra links: the topology is a plain tree.
                </TableCell>
              </TableRow>
            ) : (
              links.map((link) => (
                <TableRow key={link.id} data-testid="link-row">
                  <TableCell className="text-[12px] font-medium text-slate-800">
                    {nameOf(link.device_a_id)}
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1.5 text-[12px] text-slate-600">
                      <Link2 className="h-3 w-3 text-blue-500" />
                      {nameOf(link.device_b_id)}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                      disabled={busy}
                      onClick={() => void run(() => deleteLink(link.id))}
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
    </div>
  )
}
