import { useEffect, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { fetchSettings, updateSettings } from '@/lib/api'
import type { AppSettingsOut } from '@/types/settings'

interface SettingsFormState {
  site_name: string
  poll_interval_seconds: string
  latency_warn_ms: string
  latency_crit_ms: string
  flap_threshold: string
  failure_threshold: string
  recovery_threshold: string
}

/**
 * Settings tab: edit the singleton AppSettings row (Ticket 4.1). The user can
 * change any values via the API without a backend restart; the poll loop picks
 * them up on its next cycle.
 *
 * MVP choice (documented): on Save, ALL current form values are sent as one
 * PATCH, not just the dirty fields. Exact same effect as change-tracking for a
 * form this small, without the bookkeeping.
 */
export default function AdminSettingsTab() {
  const [form, setForm] = useState<SettingsFormState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchSettings()
      .then((settings: AppSettingsOut) => {
        if (cancelled) return
        setForm({
          site_name: settings.site_name,
          poll_interval_seconds: String(settings.poll_interval_seconds),
          latency_warn_ms: String(settings.latency_warn_ms),
          latency_crit_ms: String(settings.latency_crit_ms),
          flap_threshold: String(settings.flap_threshold),
          failure_threshold: String(settings.failure_threshold),
          recovery_threshold: String(settings.recovery_threshold),
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (form === null) return
    setSaving(true)
    setSuccess(null)
    setError(null)
    try {
      await updateSettings({
        site_name: form.site_name,
        poll_interval_seconds: Number(form.poll_interval_seconds),
        latency_warn_ms: Number(form.latency_warn_ms),
        latency_crit_ms: Number(form.latency_crit_ms),
        flap_threshold: Number(form.flap_threshold),
        failure_threshold: Number(form.failure_threshold),
        recovery_threshold: Number(form.recovery_threshold),
      })
      setSuccess('Settings updated')
      window.setTimeout(() => setSuccess(null), 4000)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  if (loadError !== null) {
    return (
      <p className="text-sm text-red-600">
        Failed to load settings: {loadError}
      </p>
    )
  }

  if (form === null) {
    return <p className="text-sm text-muted-foreground">Loading settings…</p>
  }

  return (
    <div className="max-w-lg space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Monitoring Settings</CardTitle>
          <CardDescription>
            Changes apply on the poll loop's next cycle — no restart needed.
            This matches the original tool's minimum poll interval of 5 seconds.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* noValidate: the backend is the source of truth for value sanity
              (min-5 poll interval, warn < crit). Native browser validation
              would swallow those rejections before the inline message can
              display. */}
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div className="space-y-2">
              <Label htmlFor="set-site">Site name</Label>
              <Input
                id="set-site"
                value={form.site_name}
                onChange={(e) => setForm({ ...form, site_name: e.target.value })}
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-poll">Poll interval (seconds, min 5)</Label>
                <Input
                  id="set-poll"
                  type="number"
                  step="0.5"
                  min={5}
                  value={form.poll_interval_seconds}
                  onChange={(e) =>
                    setForm({ ...form, poll_interval_seconds: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-flap">Flap threshold</Label>
                <Input
                  id="set-flap"
                  type="number"
                  min={1}
                  value={form.flap_threshold}
                  onChange={(e) =>
                    setForm({ ...form, flap_threshold: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-warn">
                  Latency warn (ms, must be &lt; crit)
                </Label>
                <Input
                  id="set-warn"
                  type="number"
                  min={0}
                  value={form.latency_warn_ms}
                  onChange={(e) =>
                    setForm({ ...form, latency_warn_ms: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-crit">Latency crit (ms)</Label>
                <Input
                  id="set-crit"
                  type="number"
                  min={0}
                  value={form.latency_crit_ms}
                  onChange={(e) =>
                    setForm({ ...form, latency_crit_ms: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-failure">
                  Failure threshold (polls, 1–10)
                </Label>
                <Input
                  id="set-failure"
                  type="number"
                  min={1}
                  max={10}
                  step={1}
                  value={form.failure_threshold}
                  onChange={(e) =>
                    setForm({ ...form, failure_threshold: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-recovery">
                  Recovery threshold (polls, 1–10)
                </Label>
                <Input
                  id="set-recovery"
                  type="number"
                  min={1}
                  max={10}
                  step={1}
                  value={form.recovery_threshold}
                  onChange={(e) =>
                    setForm({ ...form, recovery_threshold: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Debouncing: a device's status gets worse only after this many bad
              polls in a row, and better only after this many good polls in a
              row. Set both to 1 to switch debouncing off.
            </p>
            {success !== null && (
              <p className="text-sm text-green-600">{success}</p>
            )}
            {error !== null && (
              <p data-testid="settings-error" className="text-sm text-red-600">
                {error}
              </p>
            )}
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save settings'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}