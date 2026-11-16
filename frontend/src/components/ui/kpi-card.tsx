import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

const TONES = {
  neutral: {
    icon: 'border-slate-200 bg-slate-50 text-slate-500',
    accent: 'bg-slate-300',
    value: 'text-slate-950',
  },
  emerald: {
    icon: 'border-emerald-100 bg-emerald-50 text-emerald-600',
    accent: 'bg-emerald-500',
    value: 'text-slate-950',
  },
  rose: {
    icon: 'border-rose-100 bg-rose-50 text-rose-600',
    accent: 'bg-rose-500',
    value: 'text-slate-950',
  },
  amber: {
    icon: 'border-amber-100 bg-amber-50 text-amber-600',
    accent: 'bg-amber-500',
    value: 'text-slate-950',
  },
  blue: {
    icon: 'border-blue-100 bg-blue-50 text-blue-600',
    accent: 'bg-blue-500',
    value: 'text-slate-950',
  },
  violet: {
    icon: 'border-violet-100 bg-violet-50 text-violet-600',
    accent: 'bg-violet-500',
    value: 'text-slate-950',
  },
} as const

export type KpiTone = keyof typeof TONES

export default function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'neutral',
  testId,
  footer,
  className,
}: {
  label: string
  value: ReactNode
  hint?: string
  icon?: LucideIcon
  tone?: KpiTone
  testId?: string
  footer?: ReactNode
  className?: string
}) {
  const style = TONES[tone]
  return (
    <div
      data-testid={testId}
      className={cn(
        'relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 shadow-card',
        className,
      )}
    >
      <span
        className={cn(
          'absolute inset-x-0 top-0 h-[2px] opacity-80',
          style.accent,
        )}
      />
      <div className="flex items-start justify-between gap-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-500">
          {label}
        </p>
        {Icon !== undefined && (
          <span
            className={cn(
              'flex h-7 w-7 items-center justify-center rounded-lg border',
              style.icon,
            )}
          >
            <Icon className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
      <p
        className={cn(
          'mono mt-3 text-[25px] font-semibold leading-none tracking-tight',
          style.value,
        )}
      >
        {value}
      </p>
      {hint !== undefined && (
        <p className="mt-2 text-[11px] leading-snug text-slate-500">{hint}</p>
      )}
      {footer}
    </div>
  )
}
