import type { Edge, Node } from '@xyflow/react'

import type { DeviceAnomaly, DeviceOut, DeviceStatus } from '@/types/device'
import type { LinkOut } from '@/types/topology'

export type DeviceNodeData = {
  device: DeviceOut
  status?: DeviceStatus
  /** The live latency of the latest poll, shown on the node. */
  latencyMs?: number | null
  /** Set when the device is a single point of failure. */
  blastRadius?: number
  /** Set while a what-if is shown: why this device is predicted to be down. */
  predicted?: 'failed' | 'cut off'
  /** Advisory: what the anomaly detector finds unusual about the device. */
  anomaly?: DeviceAnomaly | null
  [key: string]: unknown
}

export type DeviceNode = Node<DeviceNodeData, 'device'>

// Fixed X-column per zone (deterministic manual layout for the seeded topology).
const ZONE_X: Record<string, number> = {
  edge: 0,
  'server-tier': 360,
  'ot-tier': 720,
}

const UNKNOWN_ZONE_X = 1080
// Extra links are dashed and blue, so they stand out from the grey tree edges.
const LINK_COLOR = '#2563eb'
const TREE_COLOR = '#cbd5e1'
const ROW_GAP_Y = 132
// The size of a device card (DeviceNode). React Flow hides a node until it
// knows its size, and forgets what it measured whenever the node object is
// replaced, which every status update does. A status update that arrived
// together with the first measurement left the whole graph invisible until
// the page was reloaded. With a size given here, a node is never hidden.
const NODE_WIDTH = 224
const NODE_HEIGHT = 94

const KNOWN_ZONES = Object.keys(ZONE_X)

function zoneColumn(zone: string, extraZones: string[]): number {
  if (zone in ZONE_X) return ZONE_X[zone]
  return UNKNOWN_ZONE_X + Math.max(0, extraZones.indexOf(zone)) * 360
}

/**
 * Deterministic layered layout: one vertical column per zone, devices stacked
 * in the order they appear in `devices`. No force-directed/dagre algorithm.
 *
 * Parent-child connections are solid edges. Extra links are dashed.
 */
export function computeLayout(
  devices: DeviceOut[],
  links: LinkOut[] = [],
): {
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
        initialWidth: NODE_WIDTH,
        initialHeight: NODE_HEIGHT,
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
      style: { stroke: TREE_COLOR, strokeWidth: 1.5 },
    }))

  // Like the tree edges, a link is drawn left to right (a node's handles are
  // left = in, right = out), so the device in the column further left is the
  // source. A link to a device that is not in `devices` is left out.
  const columnOf = new Map(nodes.map((node) => [node.id, node.position.x]))
  const linkEdges: Edge[] = links
    .filter(
      (link) =>
        columnOf.has(link.device_a_id) && columnOf.has(link.device_b_id),
    )
    .map((link) => {
      const leftToRight =
        (columnOf.get(link.device_a_id) ?? 0) <=
        (columnOf.get(link.device_b_id) ?? 0)
      return {
        id: `link-${link.id}`,
        source: leftToRight ? link.device_a_id : link.device_b_id,
        target: leftToRight ? link.device_b_id : link.device_a_id,
        type: 'smoothstep',
        style: {
          strokeDasharray: '6 4',
          stroke: LINK_COLOR,
          strokeWidth: 1.6,
        },
      }
    })

  return { nodes, edges: [...edges, ...linkEdges] }
}
