import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { runWhatIf } from '@/lib/api'
import type { DeviceOut } from '@/types/device'
import type { WhatIfResult } from '@/types/topology'

/** A what-if that is being shown: the devices imagined as failed, and the answer. */
export interface Simulation {
  failed: string[]
  result: WhatIfResult
}

interface WhatIfPanelProps {
  devices: DeviceOut[]
  simulation: Simulation | null
  /** Called with the new simulation to show, or null to go back to live. */
  onSimulation: (simulation: Simulation | null) => void
}

/**
 * "What if these devices failed?" Tick devices, simulate, and the graph shows
 * the predicted statuses until Reset. The backend only calculates: nothing is
 * stored and the live status is not touched.
 */
export default function WhatIfPanel({
  devices,
  simulation,
  onSimulation,
}: WhatIfPanelProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId

  const toggle = (deviceId: string) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(deviceId)) next.delete(deviceId)
      else next.add(deviceId)
      return next
    })
  }

  const simulate = async () => {
    const failed = [...selected]
    setRunning(true)
    setError(null)
    try {
      onSimulation({ failed, result: await runWhatIf(failed) })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  const reset = () => {
    setSelected(new Set())
    setError(null)
    onSimulation(null)
  }

  const rootCauses =
    simulation?.result.incidents.filter(
      (incident) => incident.category === 'root_cause',
    ) ?? []

  return (
    <aside
      data-testid="whatif-panel"
      className="flex w-72 shrink-0 flex-col gap-3 overflow-y-auto border-r bg-card p-4"
    >
      <div>
        <h2 className="text-sm font-semibold">What-if</h2>
        <p className="text-xs text-muted-foreground">
          Tick the devices to fail, then simulate. Nothing is changed on the
          network.
        </p>
      </div>

      <ul className="max-h-64 space-y-1 overflow-y-auto rounded-md border p-2">
        {devices.map((device) => (
          <li key={device.id}>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                data-testid={`whatif-device-${device.id}`}
                checked={selected.has(device.id)}
                onChange={() => toggle(device.id)}
              />
              <span className="truncate">{device.name}</span>
            </label>
          </li>
        ))}
      </ul>

      <div className="flex gap-2">
        <Button
          size="sm"
          data-testid="whatif-simulate"
          disabled={selected.size === 0 || running}
          onClick={() => void simulate()}
        >
          {running ? 'Simulating…' : 'Simulate'}
        </Button>
        <Button
          size="sm"
          variant="outline"
          data-testid="whatif-reset"
          disabled={simulation === null && selected.size === 0}
          onClick={reset}
        >
          Reset
        </Button>
      </div>

      {error !== null && (
        <p data-testid="whatif-error" className="text-sm text-red-600">
          {error}
        </p>
      )}

      {simulation !== null && (
        <div data-testid="whatif-result" className="space-y-3 text-sm">
          <div className="rounded-md border p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Total blast radius
            </p>
            <p
              data-testid="whatif-blast-radius"
              className="text-2xl font-semibold tabular-nums"
            >
              {simulation.result.total_blast_radius}
            </p>
            <p className="text-xs text-muted-foreground">
              other {simulation.result.total_blast_radius === 1 ? 'device' : 'devices'}{' '}
              cut off if {simulation.failed.map(nameOf).join(', ')}{' '}
              {simulation.failed.length === 1 ? 'fails' : 'fail'}
            </p>
          </div>

          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Predicted incidents
            </p>
            <ul className="space-y-1">
              {rootCauses.map((incident) => (
                <li
                  key={incident.device.id}
                  data-testid="whatif-root-cause"
                  className="flex items-center justify-between gap-2"
                >
                  <span className="truncate">{incident.device.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {incident.downstream_affected.length} affected
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </aside>
  )
}
