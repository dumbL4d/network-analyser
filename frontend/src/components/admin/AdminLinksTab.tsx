import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
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
      <SelectTrigger id={id} data-testid={testId} className="w-[240px]">
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
      <p className="text-sm text-muted-foreground">
        {links.length} extra {links.length === 1 ? 'link' : 'links'}, in
        addition to each device's parent. A link gives a device a second way
        to the rest of the network.
      </p>

      {loadError !== null && (
        <p className="text-sm text-red-600">Failed to load links: {loadError}</p>
      )}

      <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="link-device-a">Device</Label>
          <DeviceSelect
            id="link-device-a"
            testId="link-device-a"
            value={deviceA}
            devices={devices}
            onChange={setDeviceA}
          />
        </div>
        <div className="space-y-1">
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
          Add link
        </Button>
      </form>

      {actionError !== null && (
        <p data-testid="link-error" className="text-sm text-red-600">
          {actionError}
        </p>
      )}

      <div className="rounded-md border">
        <Table>
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
                <TableCell colSpan={3} className="text-center text-muted-foreground">
                  No extra links: the topology is a plain tree.
                </TableCell>
              </TableRow>
            ) : (
              links.map((link) => (
                <TableRow key={link.id} data-testid="link-row">
                  <TableCell>{nameOf(link.device_a_id)}</TableCell>
                  <TableCell>{nameOf(link.device_b_id)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => void run(() => deleteLink(link.id))}
                    >
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
