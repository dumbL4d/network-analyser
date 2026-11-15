import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useNavigate } from 'react-router-dom'

import { Card } from '@/components/ui/card'
import { describeAnomaly } from '@/lib/anomaly'
import { getStatusColor } from '@/lib/statusStyles'
import type { DeviceNode } from '@/lib/topologyLayout'
import { cn } from '@/lib/utils'

export function DeviceNode({ data }: NodeProps<DeviceNode>) {
  const navigate = useNavigate()
  const { device, status, blastRadius, predicted, anomaly } = data
  const statusKey = status ?? 'unknown'
  const color = getStatusColor(statusKey)

  return (
    <Card
      data-testid={`node-${device.id}`}
      onClick={() => navigate(`/devices/${device.id}`)}
      className={cn(
        'relative w-[190px] cursor-pointer border-2 px-3 py-2 shadow-sm',
        color.border,
      )}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      {blastRadius !== undefined && blastRadius > 0 && (
        <span
          data-testid={`node-spof-${device.id}`}
          title={`Single point of failure: ${blastRadius} other ${
            blastRadius === 1 ? 'device loses' : 'devices lose'
          } the network if it fails`}
          className="absolute -right-2 -top-2.5 rounded-full bg-purple-600 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white shadow"
        >
          SPOF {blastRadius}
        </span>
      )}
      {/* Advisory: the status and its colour are not affected. */}
      {anomaly && (
        <span
          data-testid={`node-anomaly-${device.id}`}
          title={`${describeAnomaly(anomaly)} (advisory: the status is unchanged)`}
          className="absolute -left-2 -top-2.5 rounded-full bg-fuchsia-600 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white shadow"
        >
          ANOMALY
        </span>
      )}
      <div className="flex items-center gap-2">
        <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', color.bg)} />
        <span className="truncate text-sm font-medium">{device.name}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between">
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {device.type}
        </span>
        <span
          data-testid={`node-status-${device.id}`}
          className={cn('text-[10px] font-semibold uppercase', color.text)}
        >
          {predicted ?? statusKey}
        </span>
      </div>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </Card>
  )
}
