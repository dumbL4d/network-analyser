import type { Edge, Node } from '@xyflow/react'

import type { DeviceOut, DeviceStatus } from '@/types/device'

export type DeviceNodeData = {
  device: DeviceOut
  status?: DeviceStatus
  [key: string]: unknown
}

export type DeviceNode = Node<DeviceNodeData, 'device'>

// Fixed X-column per zone (deterministic manual layout for the 11-device tree).
const ZONE_X: Record<string, number> = {
  edge: 0,
  'server-tier': 320,
  'ot-tier': 640,
}

const UNKNOWN_ZONE_X = 960
const ROW_GAP_Y = 110

const KNOWN_ZONES = Object.keys(ZONE_X)

function zoneColumn(zone: string, extraZones: string[]): number {
  if (zone in ZONE_X) return ZONE_X[zone]
  return UNKNOWN_ZONE_X + Math.max(0, extraZones.indexOf(zone)) * 320
}

/**
 * Deterministic layered layout: one vertical column per zone, devices stacked
 * in the order they appear in `devices`. No force-directed/dagre algorithm.
 */
export function computeLayout(devices: DeviceOut[]): {
  nodes: DeviceNode[]
  edges: Edge[]
} {
  const grouped = new Map<string, DeviceOut[]>()
  for (const device of devices) {
    const group = grouped.get(device.zone)
    if (group) {
      group.push(device)
    } else {
      grouped.set(device.zone, [device])
    }
  }

  const extraZones = [...grouped.keys()]
    .filter((zone) => !KNOWN_ZONES.includes(zone))
    .sort()

  const nodes: DeviceNode[] = []
  for (const [zone, zoneDevices] of grouped) {
    const x = zoneColumn(zone, extraZones)
    zoneDevices.forEach((device, index) => {
      nodes.push({
        id: device.id,
        type: 'device',
        position: { x, y: index * ROW_GAP_Y },
        data: { device },
      })
    })
  }

  const edges: Edge[] = devices
    .filter((device) => device.parent_id !== null)
    .map((device) => ({
      id: `${device.parent_id}->${device.id}`,
      source: device.parent_id as string,
      target: device.id,
      type: 'smoothstep',
    }))

  return { nodes, edges }
}
