import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'

import { DeviceNode } from '@/components/topology/DeviceNode'
import WhatIfPanel, { type Simulation } from '@/components/topology/WhatIfPanel'
import { useDevices } from '@/hooks/useDevices'
import { useStatusStream } from '@/hooks/useStatusStream'
import { useLinks, useSpof } from '@/hooks/useTopology'
import { computeLayout, type DeviceNodeData } from '@/lib/topologyLayout'

const nodeTypes: NodeTypes = { device: DeviceNode }

export default function TopologyView() {
  const { devices, loading, error } = useDevices()
  const { data: links } = useLinks()
  const { data: spofs } = useSpof()
  const { statuses, lastUpdate } = useStatusStream()
  // The what-if being shown instead of the live statuses, or null for live.
  const [simulation, setSimulation] = useState<Simulation | null>(null)

  // Layout depends only on the devices and links, never on live statuses.
  const { nodes: layoutNodes, edges } = useMemo(
    () => computeLayout(devices, links ?? []),
    [devices, links],
  )

  // Overlay statuses onto the stable layout nodes; positions never change.
  // Normally the live statuses; while a what-if is shown, the predicted ones.
  const nodes = useMemo(() => {
    const blastRadius = new Map(
      (spofs ?? []).map((spof) => [spof.device_id, spof.blast_radius]),
    )
    const failed = new Set(simulation?.failed)
    const cutOff = new Set(simulation?.result.unreachable_device_ids)
    return layoutNodes.map((node) => {
      const predicted: DeviceNodeData['predicted'] = failed.has(node.id)
        ? 'failed'
        : cutOff.has(node.id)
          ? 'cut off'
          : undefined
      const status: DeviceNodeData['status'] =
        simulation === null
          ? statuses[node.id]?.status
          : predicted === undefined
            ? 'healthy'
            : 'down'
      return {
        ...node,
        data: {
          ...node.data,
          status,
          predicted,
          blastRadius: blastRadius.get(node.id),
          // Anomalies are about the live readings: none while a what-if is shown.
          anomaly: simulation === null ? statuses[node.id]?.anomaly : null,
        },
      }
    })
  }, [layoutNodes, statuses, spofs, simulation])

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
    <div className="flex h-[calc(100vh-3.5rem)] w-full">
      <WhatIfPanel
        devices={devices}
        simulation={simulation}
        onSimulation={setSimulation}
      />
      <div className="relative min-w-0 flex-1">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
          >
            <Background />
            {/* The tall device column is on the right, so the minimap sits on
                the left, where the canvas is empty below the edge column. */}
            <MiniMap position="bottom-left" />
            <Controls position="bottom-right" />
          </ReactFlow>
        </ReactFlowProvider>
        <div className="pointer-events-none absolute left-4 top-4 z-10 rounded-md border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm">
          Grey: parent link · Blue dashed: extra link · SPOF n: single point
          of failure, n devices depend on it
        </div>
        {simulation !== null ? (
          <div
            data-testid="topology-mode"
            className="pointer-events-none absolute right-4 top-4 z-10 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 shadow-sm"
          >
            What-if: predicted statuses, not live
          </div>
        ) : (
          <div
            data-testid="topology-mode"
            className="pointer-events-none absolute right-4 top-4 z-10 rounded-md border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm"
          >
            {lastUpdate
              ? `${devices.length} devices · status updated ${lastUpdate.toLocaleTimeString()}`
              : `${devices.length} devices · waiting for status…`}
          </div>
        )}
      </div>
    </div>
  )
}
