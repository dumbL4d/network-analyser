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
      <div data-testid="playbook" className="mt-4 rounded-md border p-4">
        <p className="text-sm text-muted-foreground">Loading playbook…</p>
      </div>
    )
  }

  if (error !== null || playbook === null) {
    return (
      <div data-testid="playbook" className="mt-4 rounded-md border p-4">
        <p className="text-sm text-red-600">
          Failed to load playbook: {error ?? 'Unknown error'}
        </p>
      </div>
    )
  }

  const total = playbook.steps.length
  const safeStep = Math.min(currentStep, total - 1)
  const progress = total === 0 ? 0 : ((safeStep + 1) / total) * 100

  return (
    <div data-testid="playbook" className="mt-4 rounded-md border p-4">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Guided fix — step {safeStep + 1} of {total}
        </span>
        <span className="text-xs text-muted-foreground">{progress.toFixed(0)}%</span>
      </div>
      <div
        data-testid="playbook-progress"
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-blue-600 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <ol className="mt-4 space-y-2">
        {playbook.steps.map((step, index) => {
          const isCurrent = index === safeStep
          const isDone = index < safeStep
          return (
            <li
              key={step}
              data-testid={`playbook-step-${index}`}
              className={[
                'flex items-start gap-3 rounded-md border p-3 text-sm',
                isCurrent
                  ? 'border-blue-600 bg-blue-50 font-medium'
                  : isDone
                    ? 'border-transparent text-muted-foreground'
                    : 'border-transparent text-muted-foreground',
              ].join(' ')}
            >
              <span
                className={[
                  'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  isCurrent
                    ? 'bg-blue-600 text-white'
                    : isDone
                      ? 'bg-green-600 text-white'
                      : 'bg-muted text-muted-foreground',
                ].join(' ')}
              >
                {isDone ? '✓' : index + 1}
              </span>
              <span data-testid={`playbook-step-text-${index}`}>{step}</span>
            </li>
          )
        })}
      </ol>

      <div className="mt-4 flex gap-2">
        <Button
          data-testid="playbook-prev"
          variant="outline"
          size="sm"
          disabled={safeStep === 0}
          onClick={() => setCurrentStep((step) => Math.max(0, step - 1))}
        >
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
        </Button>
      </div>
    </div>
  )
}