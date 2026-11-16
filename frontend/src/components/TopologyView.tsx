import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Activity, CircleDot, FlaskConical, Waypoints } from 'lucide-react'
import { useMemo, useState } from 'react'

import { DeviceNode } from '@/components/topology/DeviceNode'
import WhatIfPanel, { type Simulation } from '@/components/topology/WhatIfPanel'
import { useDevices } from '@/hooks/useDevices'
import { useStatusStream } from '@/hooks/useStatusStream'
import { useLinks, useSpof } from '@/hooks/useTopology'
import { computeLayout, type DeviceNodeData } from '@/lib/topologyLayout'
import { cn } from '@/lib/utils'
import type { DeviceStatus } from '@/types/device'

const nodeTypes: NodeTypes = { device: DeviceNode }

const MINIMAP_COLORS: Record<DeviceStatus, string> = {
  healthy: '#10b981',
  degraded: '#f59e0b',
  down: '#f43f5e',
  unknown: '#94a3b8',
}

function TopologySkeleton() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-slate-50">
      <div className="flex flex-col items-center gap-3 text-center">
        <span className="flex h-10 w-10 animate-pulse items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-400 shadow-card">
          <Waypoints className="h-5 w-5" />
        </span>
        <div>
          <p className="text-[13px] font-medium text-slate-700">
            Building topology…
          </p>
          <p className="mt-1 text-[11px] text-slate-400">
            Loading device graph and live status channel
          </p>
        </div>
      </div>
    </div>
  )
}

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
          latencyMs:
            simulation === null ? statuses[node.id]?.latency_ms : undefined,
          predicted,
          blastRadius: blastRadius.get(node.id),
          // Anomalies are about the live readings: none while a what-if is shown.
          anomaly: simulation === null ? statuses[node.id]?.anomaly : null,
        },
      }
    })
  }, [layoutNodes, statuses, spofs, simulation])

  const healthyCount = devices.filter(
    (device) => statuses[device.id]?.status === 'healthy',
  ).length
  const issueCount = devices.filter((device) => {
    const status = statuses[device.id]?.status
    return status === 'down' || status === 'degraded'
  }).length

  if (loading) {
    return <TopologySkeleton />
  }

  if (error) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-slate-50">
        <div className="rounded-xl border border-rose-200 bg-white p-6 text-center shadow-card">
          <p className="text-sm font-semibold text-rose-700">
            Failed to load topology
          </p>
          <p className="mt-1 text-xs text-slate-500">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="absolute inset-0 flex bg-slate-50">
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
            fitViewOptions={{ padding: 0.22 }}
            minZoom={0.3}
            maxZoom={1.6}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={22}
              size={1}
              color="#cbd5e1"
            />
            <MiniMap
              position="bottom-left"
              pannable
              zoomable
              nodeColor={(node) => {
                const status =
                  (node.data as DeviceNodeData | undefined)?.status ?? 'unknown'
                return MINIMAP_COLORS[status] ?? MINIMAP_COLORS.unknown
              }}
              maskColor="rgb(248 250 252 / 0.72)"
              className="!bottom-4 !left-4"
            />
            <Controls position="bottom-right" className="!bottom-4 !right-4" />
          </ReactFlow>
        </ReactFlowProvider>

        {/* Context card */}
        <div className="pointer-events-none absolute left-4 top-4 z-10 w-[270px] rounded-xl border border-slate-200 bg-white/90 p-3.5 shadow-float backdrop-blur-md">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-400">
                <Waypoints className="h-3 w-3" />
                Network topology
              </div>
              <p className="mt-1.5 text-[15px] font-semibold tracking-tight text-slate-950">
                {devices.length} monitored devices
              </p>
            </div>
            <span
              className={cn(
                'mt-0.5 flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em]',
                issueCount > 0
                  ? 'border-amber-200 bg-amber-50 text-amber-700'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-700',
              )}
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  issueCount > 0 ? 'bg-amber-500' : 'bg-emerald-500',
                )}
              />
              {issueCount > 0 ? `${issueCount} issues` : 'Nominal'}
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-100 pt-2.5">
            <div>
              <p className="text-[9px] uppercase tracking-[0.1em] text-slate-400">
                Healthy
              </p>
              <p className="mono mt-0.5 text-[13px] font-semibold text-emerald-700">
                {healthyCount}/{devices.length}
              </p>
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-[0.1em] text-slate-400">
                Last update
              </p>
              <p className="mono mt-0.5 text-[11px] font-medium text-slate-600">
                {lastUpdate ? lastUpdate.toLocaleTimeString() : 'Waiting…'}
              </p>
            </div>
          </div>
        </div>

        {simulation !== null ? (
          <div
            data-testid="topology-mode"
            className="pointer-events-none absolute right-4 top-4 z-10 flex items-center gap-2 rounded-full border border-violet-200 bg-violet-50 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-violet-700 shadow-card"
          >
            <FlaskConical className="h-3.5 w-3.5" />
            What-if preview · not live
          </div>
        ) : (
          <div
            data-testid="topology-mode"
            className="pointer-events-none absolute right-4 top-4 z-10 flex items-center gap-2 rounded-full border border-slate-200 bg-white/90 px-3 py-1.5 text-[10px] font-medium text-slate-500 shadow-card backdrop-blur-md"
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            {lastUpdate
              ? `Live · ${devices.length} devices · ${lastUpdate.toLocaleTimeString()}`
              : `${devices.length} devices · waiting for status…`}
          </div>
        )}

        <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-4 rounded-full border border-slate-200 bg-white/90 px-3.5 py-1.5 shadow-card backdrop-blur-md">
          <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <span className="h-px w-4 bg-slate-300" />
            Parent link
          </span>
          <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <span className="h-px w-4 border-t border-dashed border-blue-500" />
            Extra link
          </span>
          <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <span className="rounded-full bg-violet-600 px-1 py-px text-[8px] font-bold text-white">
              SPOF
            </span>
            Blast radius
          </span>
          <span className="hidden items-center gap-1.5 text-[10px] text-slate-500 sm:flex">
            <CircleDot className="h-3 w-3 text-slate-400" />
            Click to inspect
          </span>
          <span className="hidden items-center gap-1.5 text-[10px] text-slate-500 xl:flex">
            <Activity className="h-3 w-3 text-blue-500" />
            Live SSE
          </span>
        </div>
      </div>
    </div>
  )
}
