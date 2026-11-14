import { cn } from '@/lib/utils'
import type { IncidentState } from '@/types/incident'

// Literal Tailwind classes so the JIT compiler sees and generates them.
const STATE_COLORS: Record<IncidentState, string> = {
  open: 'bg-red-500',
  acknowledged: 'bg-amber-500',
  resolved: 'bg-green-600',
}

export default function IncidentStateBadge({ state }: { state: IncidentState }) {
  return (
    <span
      data-testid="incident-state"
      className={cn(
        'rounded-full px-2 py-0.5 text-xs font-semibold uppercase text-white',
        STATE_COLORS[state],
      )}
    >
      {state}
    </span>
  )
}
