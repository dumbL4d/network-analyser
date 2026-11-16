import { Handle, Position, type NodeProps } from '@xyflow/react'
import { ArrowDown, ArrowUp, Minus, TriangleAlert } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import DeviceTypeIcon from '@/components/ui/device-type-icon'
import StatusBadge, { statusToneClasses } from '@/components/ui/status-badge'
import { Card } from '@/components/ui/card'
import { describeAnomaly } from '@/lib/anomaly'
import { cn } from '@/lib/utils'
import type { DeviceNode } from '@/lib/topologyLayout'

function LatencyReading({ latency }: { latency: number | null | undefined }) {
  if (latency === null || latency === undefined) {
    return <span className="text-slate-400">— ms</span>
  }
  if (latency < 40) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-700">
        <ArrowDown className="h-3 w-3" />
        {latency.toFixed(1)} ms
      </span>
    )
  }
  if (latency < 100) {
    return (
      <span className="inline-flex items-center gap-1 text-slate-600">
        <Minus className="h-3 w-3" />
        {latency.toFixed(1)} ms
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-rose-600">
      <ArrowUp className="h-3 w-3" />
      {latency.toFixed(1)} ms
    </span>
  )
}

export function DeviceNode({ data, selected }: NodeProps<DeviceNode>) {
  const navigate = useNavigate()
  const { device, status, latencyMs, blastRadius, predicted, anomaly } = data
  const statusKey = status ?? 'unknown'
  const tone = statusToneClasses(statusKey)
  const isCritical = statusKey === 'down' || predicted !== undefined

  return (
    <Card
      data-testid={`node-${device.id}`}
      onClick={() => navigate(`/devices/${device.id}`)}
      className={cn(
        'group relative w-[224px] cursor-pointer overflow-visible rounded-xl border bg-white p-0 shadow-card transition-all duration-150 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-float',
        isCritical ? 'border-rose-300/90' : 'border-slate-200',
        selected && 'ring-2 ring-blue-500/25',
      )}
    >
      <span
        className={cn(
          'absolute inset-x-3 top-0 h-[2px] rounded-full opacity-90',
          tone.dot,
        )}
      />
      <Handle
        type="target"
        position={Position.Left}
        className="!h-2 !w-2 !border-2 !border-white !bg-slate-400"
      />

      {blastRadius !== undefined && blastRadius > 0 && (
        <span
          data-testid={`node-spof-${device.id}`}
          title={`Single point of failure: ${blastRadius} other ${
            blastRadius === 1 ? 'device loses' : 'devices lose'
          } the network if it fails`}
          className="absolute -right-2 -top-2.5 z-10 rounded-full border border-violet-300 bg-violet-600 px-1.5 py-0.5 text-[9px] font-bold leading-none tracking-wide text-white shadow-sm"
        >
          SPOF {blastRadius}
        </span>
      )}
      {anomaly && (
        <span
          data-testid={`node-anomaly-${device.id}`}
          title={`${describeAnomaly(anomaly)} (advisory: the status is unchanged)`}
          className="absolute -left-2 -top-2.5 z-10 flex items-center gap-1 rounded-full border border-fuchsia-300 bg-fuchsia-600 px-1.5 py-0.5 text-[9px] font-bold leading-none tracking-wide text-white shadow-sm"
        >
          <TriangleAlert className="h-2.5 w-2.5" />
          ANOMALY
        </span>
      )}

      <div className="flex items-center gap-2.5 p-3">
        <span
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border',
            statusKey === 'down'
              ? 'border-rose-100 bg-rose-50 text-rose-600'
              : statusKey === 'degraded'
                ? 'border-amber-100 bg-amber-50 text-amber-600'
                : 'border-slate-200 bg-slate-50 text-slate-600',
          )}
        >
          <DeviceTypeIcon type={device.type} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold leading-tight tracking-tight text-slate-900">
            {device.name}
          </div>
          <div className="mono mt-1 truncate text-[10px] leading-none text-slate-500">
            {device.ip}
          </div>
        </div>
        <span
          className={cn(
            'h-2 w-2 shrink-0 rounded-full',
            tone.dot,
            statusKey === 'down' &&
              'shadow-[0_0_0_3px_rgba(244,63,94,0.12)]',
          )}
        />
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-slate-100 bg-slate-50/70 px-3 py-2">
        <span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.09em] text-slate-500">
          {device.type}
        </span>
        <span className="mono text-[10px] font-medium">
          <LatencyReading latency={latencyMs} />
        </span>
      </div>

      <div className="flex items-center justify-between gap-2 px-3 pb-2 pt-1.5">
        <span className="text-[9px] uppercase tracking-[0.1em] text-slate-400">
          {device.zone}
        </span>
        <span data-testid={`node-status-${device.id}`}>
          {predicted !== undefined ? (
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em]',
                predicted === 'failed'
                  ? 'border-rose-200 bg-rose-50 text-rose-700'
                  : 'border-amber-200 bg-amber-50 text-amber-700',
              )}
            >
              {predicted}
            </span>
          ) : (
            <StatusBadge status={statusKey} className="px-1.5 py-0 text-[9px]" />
          )}
        </span>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!h-2 !w-2 !border-2 !border-white !bg-slate-400"
      />
    </Card>
  )
}
