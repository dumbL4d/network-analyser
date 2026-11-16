import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { useDevices } from '@/hooks/useDevices'
import { usePolled } from '@/hooks/usePolled'
import {
  chaosDegrade,
  chaosFail,
  chaosRestoreAll,
  chaosScenario,
  fetchChaosState,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import type { ChaosFaultKind } from '@/types/chaos'

// Each look makes the agent ask every simulated device, so not too often.
// After an action the state is re-read at once.
const STATE_POLL_MS = 10_000

// Literal Tailwind classes so the JIT compiler sees and generates them.
const KIND_STYLE: Record<ChaosFaultKind, { label: string; color: string }> = {
  failed: { label: 'Failed', color: 'bg-red-500' },
  cut_off: { label: 'Cut off', color: 'bg-amber-500' },
  flapping: { label: 'Flapping', color: 'bg-blue-500' },
  degraded: { label: 'Degraded', color: 'bg-yellow-600' },
  leftover: { label: 'Left over', color: 'bg-gray-500' },
}

/**
 * Admin tab for fault injection on the simulated network: presets, failing
 * or slowing down one device, the faults in place, and Restore all.
 *
 * The backend decides what a failure takes with it (everything it cuts off)
 * and a separate chaos agent carries it out. When that agent is not running
 * the backend answers 503; its message is shown here and the controls are
 * switched off.
 */
export default function AdminChaosTab() {
  const { devices } = useDevices()
  const {
    data: chaos,
    error: stateError,
    refresh,
  } = usePolled(fetchChaosState, 'chaos-state', STATE_POLL_MS)

  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [failDevice, setFailDevice] = useState('')
  const [degradeDevice, setDegradeDevice] = useState('')
  const [delayMs, setDelayMs] = useState('200')
  const [jitterMs, setJitterMs] = useState('40')
  const [lossPct, setLossPct] = useState('2')

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId

  // Only the devices that have a simulated container can be broken.
  const controllable = devices.filter((device) =>
    chaos?.controllable_device_ids.includes(device.id),
  )
  const faults = chaos?.faults ?? []
  const available = chaos !== null && stateError === null

  // Run an action, then re-read the state. On failure show what the backend said.
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setActionError(null)
    try {
      await action()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
    } finally {
      refresh()
      setBusy(false)
    }
  }

  const handleFail = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(() => chaosFail([failDevice]))
  }

  const handleDegrade = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void run(() =>
      chaosDegrade(
        degradeDevice,
        Number(delayMs),
        Number(jitterMs),
        Number(lossPct),
      ),
    )
  }

  const deviceOptions = controllable.map((device) => (
    <SelectItem key={device.id} value={device.id}>
      {device.name}
    </SelectItem>
  ))

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Break the simulated network on purpose and watch the monitoring
          react. A failed device takes everything with it that it cuts off, so
          a failure looks the way it would on real hardware. Nothing here
          touches a device that is not simulated.
        </p>
        <Button
          variant="destructive"
          size="lg"
          data-testid="chaos-restore-all"
          disabled={busy || !available}
          onClick={() => void run(chaosRestoreAll)}
        >
          Restore all
        </Button>
      </div>

      {stateError !== null && (
        <div
          data-testid="chaos-unavailable"
          className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
        >
          <p className="font-medium">Fault injection is not available.</p>
          <p className="mt-1">{stateError}</p>
        </div>
      )}

      {actionError !== null && (
        <p data-testid="chaos-error" className="text-sm text-red-600">
          {actionError}
        </p>
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Scenarios
        </h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {(chaos?.scenarios ?? []).map((scenario) => (
            <Card key={scenario.name} data-testid={`chaos-scenario-${scenario.name}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{scenario.title}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {scenario.description}
                </p>
                <Button
                  size="sm"
                  disabled={busy || !available}
                  onClick={() => void run(() => chaosScenario(scenario.name))}
                >
                  Run
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Fail a device</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleFail} className="flex flex-wrap items-end gap-3">
              <div className="space-y-1">
                <Label htmlFor="chaos-fail-device">Device</Label>
                <Select value={failDevice} onValueChange={setFailDevice}>
                  <SelectTrigger
                    id="chaos-fail-device"
                    data-testid="chaos-fail-device"
                    className="w-[220px]"
                  >
                    <SelectValue placeholder="Select a device" />
                  </SelectTrigger>
                  <SelectContent>{deviceOptions}</SelectContent>
                </Select>
              </div>
              <Button
                type="submit"
                variant="outline"
                data-testid="chaos-fail"
                disabled={busy || !available || failDevice === ''}
              >
                Fail
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Degrade a device</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleDegrade} className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="chaos-degrade-device">Device</Label>
                <Select value={degradeDevice} onValueChange={setDegradeDevice}>
                  <SelectTrigger
                    id="chaos-degrade-device"
                    data-testid="chaos-degrade-device"
                    className="w-[220px]"
                  >
                    <SelectValue placeholder="Select a device" />
                  </SelectTrigger>
                  <SelectContent>{deviceOptions}</SelectContent>
                </Select>
              </div>
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label htmlFor="chaos-delay">Delay (ms)</Label>
                  <Input
                    id="chaos-delay"
                    type="number"
                    min={0}
                    max={5000}
                    className="w-24"
                    value={delayMs}
                    onChange={(e) => setDelayMs(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="chaos-jitter">Jitter (ms)</Label>
                  <Input
                    id="chaos-jitter"
                    type="number"
                    min={0}
                    max={5000}
                    className="w-24"
                    value={jitterMs}
                    onChange={(e) => setJitterMs(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="chaos-loss">Loss (%)</Label>
                  <Input
                    id="chaos-loss"
                    type="number"
                    min={0}
                    max={100}
                    step="0.1"
                    className="w-24"
                    value={lossPct}
                    onChange={(e) => setLossPct(e.target.value)}
                  />
                </div>
                <Button
                  type="submit"
                  variant="outline"
                  data-testid="chaos-degrade"
                  disabled={busy || !available || degradeDevice === ''}
                >
                  Degrade
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Active faults ({faults.length})
        </h3>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead>Fault</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {faults.length === 0 ? (
                <TableRow
                  data-testid={available ? 'chaos-no-faults' : 'chaos-faults-unknown'}
                >
                  <TableCell colSpan={3} className="text-center text-muted-foreground">
                    {available
                      ? 'No faults in place: every simulated device is running normally.'
                      : stateError === null
                        ? 'Asking the chaos agent…'
                        : 'Unknown while fault injection is not available.'}
                  </TableCell>
                </TableRow>
              ) : (
                faults.map((fault) => (
                  <TableRow
                    key={`${fault.device_id}:${fault.kind}`}
                    data-testid="chaos-fault"
                  >
                    <TableCell className="font-medium">
                      {nameOf(fault.device_id)}
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-xs font-semibold text-white',
                          KIND_STYLE[fault.kind].color,
                        )}
                      >
                        {KIND_STYLE[fault.kind].label}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {fault.detail}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  )
}
