import { Handle, Position, type NodeProps } from '@xyflow/react'
import { useNavigate } from 'react-router-dom'

import { Card } from '@/components/ui/card'
import { getStatusColor } from '@/lib/statusStyles'
import type { DeviceNode } from '@/lib/topologyLayout'
import { cn } from '@/lib/utils'

export function DeviceNode({ data }: NodeProps<DeviceNode>) {
  const navigate = useNavigate()
  const { device, status } = data
  const statusKey = status ?? 'unknown'
  const color = getStatusColor(statusKey)

  return (
    <Card
      data-testid={`node-${device.id}`}
      onClick={() => navigate(`/devices/${device.id}`)}
      className={cn(
        'w-[190px] cursor-pointer border-2 px-3 py-2 shadow-sm',
        color.border,
      )}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
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
          {statusKey}
        </span>
      </div>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </Card>
  )
}
