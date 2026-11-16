import {
  Check,
  ChevronDown,
  FlaskConical,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  RotateCcw,
  Search,
} from 'lucide-react'
import { useState } from 'react'

import DeviceTypeIcon from '@/components/ui/device-type-icon'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { runWhatIf } from '@/lib/api'
import { cn } from '@/lib/utils'
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
  const [collapsed, setCollapsed] = useState(false)
  const [query, setQuery] = useState('')

  const nameOf = (deviceId: string) =>
    devices.find((device) => device.id === deviceId)?.name ?? deviceId

  const filteredDevices = devices.filter((device) => {
    const needle = query.trim().toLowerCase()
    if (needle === '') return true
    return (
      device.name.toLowerCase().includes(needle) ||
      device.id.toLowerCase().includes(needle) ||
      device.zone.toLowerCase().includes(needle) ||
      device.type.toLowerCase().includes(needle)
    )
  })

  const toggle = (deviceId: string) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(deviceId)) next.delete(deviceId)
      else next.add(deviceId)
      return next
    })
  }

  const toggleVisible = () => {
    setSelected((previous) => {
      const next = new Set(previous)
      const allSelected = filteredDevices.every((device) => next.has(device.id))
      for (const device of filteredDevices) {
        if (allSelected) next.delete(device.id)
        else next.add(device.id)
      }
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

  if (collapsed) {
    return (
      <aside
        data-testid="whatif-panel"
        className="flex w-14 shrink-0 flex-col items-center gap-3 border-r border-slate-200 bg-white py-3"
      >
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900"
          title="Open what-if simulator"
          aria-label="Open what-if simulator"
        >
          <PanelLeftOpen className="h-4 w-4" />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-50 text-violet-600">
          <FlaskConical className="h-4 w-4" />
        </div>
        <span className="mt-1 [writing-mode:vertical-rl] text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          What-if
        </span>
        {selected.size > 0 && (
          <span className="mono flex h-5 min-w-5 items-center justify-center rounded-full bg-violet-600 px-1 text-[10px] font-semibold text-white">
            {selected.size}
          </span>
        )}
      </aside>
    )
  }

  return (
    <aside
      data-testid="whatif-panel"
      className="flex w-[308px] shrink-0 flex-col border-r border-slate-200 bg-white"
    >
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3.5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-violet-100 bg-violet-50 text-violet-600">
            <FlaskConical className="h-4 w-4" />
          </span>
          <div>
            <h2 className="text-[13px] font-semibold leading-none text-slate-950">
              What-if simulator
            </h2>
            <p className="mt-1.5 text-[10px] font-medium uppercase tracking-[0.1em] text-slate-400">
              Fault impact analysis
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          title="Collapse what-if simulator"
          aria-label="Collapse what-if simulator"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      <div className="border-b border-slate-100 px-4 py-3">
        <p className="text-[11px] leading-relaxed text-slate-500">
          Select devices to imagine them offline. The graph previews blast
          radius without changing the live network.
        </p>
      </div>

      <div className="flex items-center gap-2 px-4 py-3">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter devices…"
            className="h-8 pl-8 text-[11px]"
            aria-label="Filter devices for simulation"
          />
        </div>
        <button
          type="button"
          onClick={toggleVisible}
          className="h-8 shrink-0 rounded-lg border border-slate-200 px-2 text-[10px] font-semibold text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900"
          title="Select or clear visible devices"
        >
          {filteredDevices.length > 0 &&
          filteredDevices.every((device) => selected.has(device.id))
            ? 'Clear'
            : 'All'}
        </button>
      </div>

      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-3">
        {filteredDevices.length === 0 ? (
          <li className="px-3 py-8 text-center text-[11px] text-slate-400">
            No devices match “{query}”.
          </li>
        ) : (
          filteredDevices.map((device) => {
            const isSelected = selected.has(device.id)
            return (
              <li key={device.id}>
                <label
                  className={cn(
                    'flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 transition-colors',
                    isSelected ? 'bg-violet-50/80' : 'hover:bg-slate-50',
                  )}
                >
                  <span className="relative flex shrink-0 items-center">
                    <input
                      type="checkbox"
                      data-testid={`whatif-device-${device.id}`}
                      checked={isSelected}
                      onChange={() => toggle(device.id)}
                      className="peer sr-only"
                    />
                    <span
                      className={cn(
                        'flex h-4 w-4 items-center justify-center rounded border transition-all',
                        isSelected
                          ? 'border-violet-600 bg-violet-600 text-white'
                          : 'border-slate-300 bg-white text-transparent',
                      )}
                    >
                      <Check className="h-3 w-3" strokeWidth={3} />
                    </span>
                  </span>
                  <span
                    className={cn(
                      'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border',
                      isSelected
                        ? 'border-violet-200 bg-white text-violet-600'
                        : 'border-slate-200 bg-slate-50 text-slate-500',
                    )}
                  >
                    <DeviceTypeIcon type={device.type} className="h-3.5 w-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-medium leading-tight text-slate-800">
                      {device.name}
                    </span>
                    <span className="mono mt-1 block truncate text-[9px] leading-none text-slate-400">
                      {device.id} · {device.zone}
                    </span>
                  </span>
                </label>
              </li>
            )
          })
        )}
      </ul>

      <div className="border-t border-slate-100 bg-slate-50/60 p-3">
        <div className="mb-2.5 flex items-center justify-between px-0.5">
          <span className="text-[10px] font-medium uppercase tracking-[0.09em] text-slate-400">
            {selected.size} selected
          </span>
          <span className="mono text-[10px] text-slate-400">
            {devices.length} devices
          </span>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            data-testid="whatif-simulate"
            disabled={selected.size === 0 || running}
            onClick={() => void simulate()}
            className="flex-1 bg-violet-600 hover:bg-violet-700 active:bg-violet-800"
          >
            <Play className="h-3.5 w-3.5" />
            {running ? 'Simulating…' : 'Simulate'}
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid="whatif-reset"
            disabled={simulation === null && selected.size === 0}
            onClick={reset}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </Button>
        </div>
      </div>

      {error !== null && (
        <p
          data-testid="whatif-error"
          className="border-t border-rose-100 bg-rose-50 px-4 py-2.5 text-[11px] font-medium text-rose-700"
        >
          {error}
        </p>
      )}

      {simulation !== null && (
        <div
          data-testid="whatif-result"
          className="max-h-[42%] space-y-3 overflow-y-auto border-t border-slate-200 bg-white p-4"
        >
          <div className="rounded-xl border border-violet-100 bg-violet-50/70 p-3.5">
            <div className="flex items-center justify-between">
              <p className="label-caps !text-violet-500">Total blast radius</p>
              <ChevronDown className="h-3.5 w-3.5 text-violet-400" />
            </div>
            <p
              data-testid="whatif-blast-radius"
              className="mono mt-2 text-[30px] font-semibold leading-none tracking-tight text-violet-800"
            >
              {simulation.result.total_blast_radius}
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-violet-700/80">
              other{' '}
              {simulation.result.total_blast_radius === 1 ? 'device' : 'devices'}{' '}
              cut off if {simulation.failed.map(nameOf).join(', ')}{' '}
              {simulation.failed.length === 1 ? 'fails' : 'fail'}
            </p>
          </div>

          <div>
            <p className="label-caps mb-2">Predicted incidents</p>
            {rootCauses.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-200 px-3 py-3 text-[11px] text-slate-400">
                No root-cause incidents predicted.
              </p>
            ) : (
              <ul className="space-y-1">
                {rootCauses.map((incident) => (
                  <li
                    key={incident.device.id}
                    data-testid="whatif-root-cause"
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-500" />
                      <span className="truncate text-[11px] font-medium text-slate-700">
                        {incident.device.name}
                      </span>
                    </span>
                    <span className="mono shrink-0 text-[10px] text-slate-400">
                      {incident.downstream_affected.length} affected
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </aside>
  )
}
