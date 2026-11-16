import { cn } from '@/lib/utils'
import type { IncidentState } from '@/types/incident'

// Literal Tailwind classes so the JIT compiler sees and generates them.
const STATE_STYLES: Record<IncidentState, { badge: string; dot: string }> = {
  open: {
    badge: 'border-rose-200 bg-rose-50 text-rose-700',
    dot: 'bg-rose-500',
  },
  acknowledged: {
    badge: 'border-amber-200 bg-amber-50 text-amber-700',
    dot: 'bg-amber-500',
  },
  resolved: {
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    dot: 'bg-emerald-500',
  },
}

export default function IncidentStateBadge({ state }: { state: IncidentState }) {
  const style = STATE_STYLES[state]
  return (
    <span
      data-testid="incident-state"
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]',
        style.badge,
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', style.dot)} />
      {state}
    </span>
  )
}
