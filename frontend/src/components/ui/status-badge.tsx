import { cn } from '@/lib/utils'
import type { DeviceStatus } from '@/types/device'

const BADGE_STYLES: Record<
  DeviceStatus,
  { badge: string; dot: string; label: string }
> = {
  healthy: {
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    dot: 'bg-emerald-500',
    label: 'Healthy',
  },
  degraded: {
    badge: 'border-amber-200 bg-amber-50 text-amber-700',
    dot: 'bg-amber-500',
    label: 'Degraded',
  },
  down: {
    badge: 'border-rose-200 bg-rose-50 text-rose-700',
    dot: 'bg-rose-500',
    label: 'Down',
  },
  unknown: {
    badge: 'border-slate-200 bg-slate-50 text-slate-600',
    dot: 'bg-slate-400',
    label: 'Unknown',
  },
}

export function statusToneClasses(status: DeviceStatus) {
  return BADGE_STYLES[status] ?? BADGE_STYLES.unknown
}

export default function StatusBadge({
  status,
  className,
  showLabel = true,
  testId,
}: {
  status: DeviceStatus
  className?: string
  showLabel?: boolean
  testId?: string
}) {
  const tone = BADGE_STYLES[status] ?? BADGE_STYLES.unknown
  return (
    <span
      data-testid={testId}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]',
        tone.badge,
        className,
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full',
          tone.dot,
          status === 'down' && 'shadow-[0_0_0_2px_rgba(244,63,94,0.15)]',
        )}
      />
      {showLabel ? tone.label : null}
    </span>
  )
}
