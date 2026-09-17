import type { DeviceStatus } from '@/types/device'

export interface StatusColor {
  bg: string
  border: string
  text: string
}

// Literal Tailwind classes so the JIT compiler sees and generates them.
const STATUS_COLORS: Record<DeviceStatus, StatusColor> = {
  healthy: {
    bg: 'bg-green-500',
    border: 'border-green-500',
    text: 'text-green-700',
  },
  degraded: {
    bg: 'bg-amber-500',
    border: 'border-amber-500',
    text: 'text-amber-700',
  },
  down: { bg: 'bg-red-500', border: 'border-red-500', text: 'text-red-700' },
  unknown: {
    bg: 'bg-gray-400',
    border: 'border-gray-400',
    text: 'text-gray-600',
  },
}

/** Shared status colour mapping used by the topology and device detail views. */
export function getStatusColor(status: DeviceStatus): StatusColor {
  return STATUS_COLORS[status] ?? STATUS_COLORS.unknown
}
