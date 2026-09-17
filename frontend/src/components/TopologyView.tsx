import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'

import { DeviceNode } from '@/components/topology/DeviceNode'
import { useDevices } from '@/hooks/useDevices'
import { useStatusStream } from '@/hooks/useStatusStream'
import { computeLayout } from '@/lib/topologyLayout'

const nodeTypes: NodeTypes = { device: DeviceNode }

export default function TopologyView() {
  const { devices, loading, error } = useDevices()
  const { statuses, lastUpdate } = useStatusStream()

  // Layout depends only on the (static) device list, never on live statuses.
  const { nodes: layoutNodes, edges } = useMemo(
    () => computeLayout(devices),
    [devices],
  )

  // Overlay live statuses onto the stable layout nodes; positions never change.
  const nodes = useMemo(
    () =>
      layoutNodes.map((node) => ({
        ...node,
        data: { ...node.data, status: statuses[node.id]?.status },
      })),
    [layoutNodes, statuses],
  )

  if (loading) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading topology...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-[calc(100vh-3.5rem)] items-center justify-center">
        <p className="text-sm text-red-600">
          Failed to load topology: {error}
        </p>
      </div>
    )
  }

  return (
    <div className="relative h-[calc(100vh-3.5rem)] w-full">
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
        >
          <Background />
          <MiniMap />
          <Controls />
        </ReactFlow>
      </ReactFlowProvider>
      <div className="pointer-events-none absolute right-4 top-4 z-10 rounded-md border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm">
        {lastUpdate
          ? `${devices.length} devices · status updated ${lastUpdate.toLocaleTimeString()}`
          : `${devices.length} devices · waiting for status…`}
      </div>
    </div>
  )
}
