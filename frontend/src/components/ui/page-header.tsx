import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: string
  description?: string
  eyebrow?: ReactNode
  actions?: ReactNode
  className?: string
}

export default function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        'mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between',
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow !== undefined && (
          <div className="mb-2 flex items-center gap-2">{eyebrow}</div>
        )}
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.025em] text-slate-950">
          {title}
        </h1>
        {description !== undefined && (
          <p className="mt-1.5 max-w-2xl text-[13px] leading-relaxed text-slate-500">
            {description}
          </p>
        )}
      </div>
      {actions !== undefined && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  )
}
