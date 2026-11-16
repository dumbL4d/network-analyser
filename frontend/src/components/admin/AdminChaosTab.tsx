import { FlaskConical, RotateCcw, TriangleAlert, Zap } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
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
const KIND_STYLE: Record<
  ChaosFaultKind,
  { label: string; badge: string; dot: string }
> = {
  failed: {
    label: 'Failed',
    badge: 'border-rose-200 bg-rose-50 text-rose-700',
    dot: 'bg-rose-500',
  },
  cut_off: {
    label: 'Cut off',
    badge: 'border-amber-200 bg-amber-50 text-amber-700',
    dot: 'bg-amber-500',
  },
  flapping: {
    label: 'Flapping',
    badge: 'border-blue-200 bg-blue-50 text-blue-700',
    dot: 'bg-blue-500',
  },
  degraded: {
    label: 'Degraded',
    badge: 'border-yellow-200 bg-yellow-50 text-yellow-800',
    dot: 'bg-yellow-500',
  },
  leftover: {
    label: 'Left over',
    badge: 'border-slate-200 bg-slate-50 text-slate-600',
    dot: 'bg-slate-400',
  },
}

function SectionTitle({
  title,
  hint,
  count,
}: {
  title: string
  hint?: string
  count?: number
}) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
        {title}
      </h3>
      {count !== undefined && (
        <span className="mono rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold text-slate-500">
          {count}
        </span>
      )}
      <span className="h-px flex-1 bg-slate-200" />
      {hint !== undefined && (
        <span className="text-[10px] text-slate-400">{hint}</span>
      )}
    </div>
  )
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
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50/50 px-4 py-3.5">
        <div className="flex max-w-2xl items-start gap-2.5">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-rose-200 bg-white text-rose-600">
            <Zap className="h-3.5 w-3.5" />
          </span>
          <p className="text-[11px] leading-relaxed text-rose-900/80">
            Break the simulated network on purpose and watch the monitoring
            react. A failed device takes everything with it that it cuts off, so
            a failure looks the way it would on real hardware. Nothing here
            touches a device that is not simulated.
          </p>
        </div>
        <Button
          variant="destructive"
          size="sm"
          data-testid="chaos-restore-all"
          disabled={busy || !available}
          onClick={() => void run(chaosRestoreAll)}
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Restore all
        </Button>
      </div>

      {stateError !== null && (
        <div
          data-testid="chaos-unavailable"
          className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-[12px] text-amber-900"
        >
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
          <div>
            <p className="font-semibold">Fault injection is not available.</p>
            <p className="mt-0.5 text-amber-800/80">{stateError}</p>
          </div>
        </div>
      )}

      {actionError !== null && (
        <p
          data-testid="chaos-error"
          className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700"
        >
          {actionError}
        </p>
      )}

      <section>
        <SectionTitle title="Scenarios" hint="One-click outage patterns" />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {(chaos?.scenarios ?? []).map((scenario) => (
            <Card
              key={scenario.name}
              data-testid={`chaos-scenario-${scenario.name}`}
              className="flex flex-col justify-between p-4 transition-shadow hover:shadow-float"
            >
              <div className="flex items-start gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-violet-100 bg-violet-50 text-violet-600">
                  <FlaskConical className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-[13px] font-semibold text-slate-900">
                    {scenario.title}
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                    {scenario.description}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex justify-end">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !available}
                  onClick={() => void run(() => chaosScenario(scenario.name))}
                >
                  Run
                </Button>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-5 py-4">
            <p className="text-[13px] font-semibold text-slate-900">
              Fail a device
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Take a simulated device down and cascade the outage downstream.
            </p>
          </div>
          <form
            onSubmit={handleFail}
            className="flex flex-wrap items-end gap-3 p-5"
          >
            <div className="space-y-1.5">
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
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-slate-100 px-5 py-4">
            <p className="text-[13px] font-semibold text-slate-900">
              Degrade a device
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Add latency, jitter, and packet loss without taking it down.
            </p>
          </div>
          <form onSubmit={handleDegrade} className="space-y-3 p-5">
            <div className="space-y-1.5">
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
              <div className="space-y-1.5">
                <Label htmlFor="chaos-delay">Delay (ms)</Label>
                <Input
                  id="chaos-delay"
                  type="number"
                  min={0}
                  max={5000}
                  className="mono w-24 text-[12px]"
                  value={delayMs}
                  onChange={(e) => setDelayMs(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="chaos-jitter">Jitter (ms)</Label>
                <Input
                  id="chaos-jitter"
                  type="number"
                  min={0}
                  max={5000}
                  className="mono w-24 text-[12px]"
                  value={jitterMs}
                  onChange={(e) => setJitterMs(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="chaos-loss">Loss (%)</Label>
                <Input
                  id="chaos-loss"
                  type="number"
                  min={0}
                  max={100}
                  step="0.1"
                  className="mono w-24 text-[12px]"
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
        </Card>
      </section>

      <section>
        <SectionTitle title="Active faults" count={faults.length} />
        <Card className="overflow-hidden">
          <Table className="table-density">
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
                  data-testid={
                    available ? 'chaos-no-faults' : 'chaos-faults-unknown'
                  }
                >
                  <TableCell
                    colSpan={3}
                    className="py-10 text-center text-[12px] text-slate-500"
                  >
                    {available
                      ? 'No faults in place: every simulated device is running normally.'
                      : stateError === null
                        ? 'Asking the chaos agent…'
                        : 'Unknown while fault injection is not available.'}
                  </TableCell>
                </TableRow>
              ) : (
                faults.map((fault) => {
                  const style = KIND_STYLE[fault.kind]
                  return (
                    <TableRow
                      key={`${fault.device_id}:${fault.kind}`}
                      data-testid="chaos-fault"
                    >
                      <TableCell className="text-[12px] font-medium text-slate-800">
                        {nameOf(fault.device_id)}
                      </TableCell>
                      <TableCell>
                        <span
                          className={cn(
                            'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]',
                            style.badge,
                          )}
                        >
                          <span
                            className={cn('h-1.5 w-1.5 rounded-full', style.dot)}
                          />
                          {style.label}
                        </span>
                      </TableCell>
                      <TableCell className="text-[11px] text-slate-500">
                        {fault.detail}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </Card>
      </section>
    </div>
  )
}
