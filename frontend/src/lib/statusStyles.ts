import type { DeviceStatus } from '@/types/device'

export interface StatusColor {
  bg: string
  border: string
  text: string
}

// Literal Tailwind classes so the JIT compiler sees and generates them.
const STATUS_COLORS: Record<DeviceStatus, StatusColor> = {
  healthy: {
    bg: 'bg-emerald-500',
    border: 'border-emerald-400',
    text: 'text-emerald-700',
  },
  degraded: {
    bg: 'bg-amber-500',
    border: 'border-amber-400',
    text: 'text-amber-700',
  },
  down: {
    bg: 'bg-rose-500',
    border: 'border-rose-400',
    text: 'text-rose-700',
  },
  unknown: {
    bg: 'bg-slate-400',
    border: 'border-slate-300',
    text: 'text-slate-500',
  },
}

/** Shared status colour mapping used by the topology and device detail views. */
export function getStatusColor(status: DeviceStatus): StatusColor {
  return STATUS_COLORS[status] ?? STATUS_COLORS.unknown
}
