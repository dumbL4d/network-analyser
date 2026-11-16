import { ArrowLeft, ArrowRight, Check, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { fetchPlaybook } from '@/lib/api'
import type { PlaybookOut } from '@/types/incident'

type IncidentState = 'down' | 'degraded'

interface GuidedFixPlaybookProps {
  deviceType: string
  state: IncidentState
}

/**
 * Step-by-step guided-fix checklist for one incident.
 *
 * The parent keys this component by `${device.id}:${status}` and mounts it
 * only while a card is expanded, so every open (and every status change while
 * open) is a fresh mount: `currentStepIndex` starts at 0 and the playbook is
 * re-fetched for the new device/state. A previous device's progress therefore
 * never leaks into a new one. The effect's `[deviceType, state]` deps are
 * belt-and-braces for any caller that mounts without a key.
 */
export default function GuidedFixPlaybook({
  deviceType,
  state,
}: GuidedFixPlaybookProps) {
  const [playbook, setPlaybook] = useState<PlaybookOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [currentStep, setCurrentStep] = useState(0)

  useEffect(() => {
    let cancelled = false

    fetchPlaybook(deviceType, state)
      .then((data) => {
        if (!cancelled) setPlaybook(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [deviceType, state])

  if (loading) {
    return (
      <div
        data-testid="playbook"
        className="mt-4 rounded-xl border border-violet-200 bg-violet-50/40 p-4"
      >
        <p className="text-[12px] text-slate-500">Loading playbook…</p>
      </div>
    )
  }

  if (error !== null || playbook === null) {
    return (
      <div
        data-testid="playbook"
        className="mt-4 rounded-xl border border-rose-200 bg-rose-50/50 p-4"
      >
        <p className="text-[12px] text-rose-700">
          Failed to load playbook: {error ?? 'Unknown error'}
        </p>
      </div>
    )
  }

  const total = playbook.steps.length
  const safeStep = Math.min(currentStep, total - 1)
  const progress = total === 0 ? 0 : ((safeStep + 1) / total) * 100

  return (
    <div
      data-testid="playbook"
      className="mt-4 overflow-hidden rounded-xl border border-violet-200 bg-violet-50/30"
    >
      <div className="border-b border-violet-100 bg-violet-50/60 px-4 py-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-violet-700">
            <Sparkles className="h-3 w-3" />
            Guided fix — step {safeStep + 1} of {total}
          </span>
          <span className="mono text-[10px] font-semibold text-violet-600">
            {progress.toFixed(0)}%
          </span>
        </div>
        <div
          data-testid="playbook-progress"
          className="h-1.5 w-full overflow-hidden rounded-full bg-violet-200/60"
        >
          <div
            className="h-full rounded-full bg-violet-600 transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <ol className="space-y-2 p-4">
        {playbook.steps.map((step, index) => {
          const isCurrent = index === safeStep
          const isDone = index < safeStep
          return (
            <li
              key={step}
              data-testid={`playbook-step-${index}`}
              className={[
                'flex items-start gap-3 rounded-lg border px-3 py-2.5 text-[12px] transition-colors',
                isCurrent
                  ? 'border-blue-200 bg-white font-medium text-slate-900 shadow-card'
                  : isDone
                    ? 'border-transparent text-slate-400'
                    : 'border-transparent text-slate-500',
              ].join(' ')}
            >
              <span
                className={[
                  'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold',
                  isCurrent
                    ? 'bg-blue-600 text-white'
                    : isDone
                      ? 'bg-emerald-500 text-white'
                      : 'border border-slate-200 bg-white text-slate-400',
                ].join(' ')}
              >
                {isDone ? <Check className="h-3 w-3" /> : index + 1}
              </span>
              <span data-testid={`playbook-step-text-${index}`}>{step}</span>
            </li>
          )
        })}
      </ol>

      <div className="flex items-center justify-between gap-2 border-t border-violet-100 px-4 py-3">
        <span className="text-[10px] text-slate-400">
          {safeStep === total - 1
            ? 'Checklist complete'
            : `${total - safeStep - 1} step${total - safeStep - 1 === 1 ? '' : 's'} remaining`}
        </span>
        <div className="flex gap-2">
          <Button
            data-testid="playbook-prev"
            variant="outline"
            size="sm"
            disabled={safeStep === 0}
            onClick={() => setCurrentStep((step) => Math.max(0, step - 1))}
          >
            <ArrowLeft className="h-3 w-3" />
            Back
          </Button>
          <Button
            data-testid="playbook-next"
            variant={safeStep === total - 1 ? 'default' : 'outline'}
            size="sm"
            onClick={() =>
              setCurrentStep((step) => Math.min(total - 1, step + 1))
            }
          >
            {safeStep === total - 1 ? 'Done' : 'Next'}
            {safeStep !== total - 1 && <ArrowRight className="h-3 w-3" />}
          </Button>
        </div>
      </div>
    </div>
  )
}
