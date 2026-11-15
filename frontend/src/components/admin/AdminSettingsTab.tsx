import { useEffect, useState, type FormEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
  pings_per_cycle: string
  ping_gap_ms: string
  loss_warn_pct: string
  jitter_warn_ms: string
  anomaly_enabled: boolean
  anomaly_detector: AppSettingsOut['anomaly_detector']
  anomaly_k: string
  anomaly_m: string
  anomaly_alpha: string
  anomaly_window: string
}

/**
 * Settings tab: edit the singleton AppSettings row. The user can
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
          pings_per_cycle: String(settings.pings_per_cycle),
          ping_gap_ms: String(settings.ping_gap_ms),
          loss_warn_pct: String(settings.loss_warn_pct),
          jitter_warn_ms: String(settings.jitter_warn_ms),
          anomaly_enabled: settings.anomaly_enabled,
          anomaly_detector: settings.anomaly_detector,
          anomaly_k: String(settings.anomaly_k),
          anomaly_m: String(settings.anomaly_m),
          anomaly_alpha: String(settings.anomaly_alpha),
          anomaly_window: String(settings.anomaly_window),
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
        pings_per_cycle: Number(form.pings_per_cycle),
        ping_gap_ms: Number(form.ping_gap_ms),
        loss_warn_pct: Number(form.loss_warn_pct),
        jitter_warn_ms: Number(form.jitter_warn_ms),
        anomaly_enabled: form.anomaly_enabled,
        anomaly_detector: form.anomaly_detector,
        anomaly_k: Number(form.anomaly_k),
        anomaly_m: Number(form.anomaly_m),
        anomaly_alpha: Number(form.anomaly_alpha),
        anomaly_window: Number(form.anomaly_window),
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
              (min-5 poll interval, warn < crit, probes that fit in the poll
              interval). Native browser validation
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
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-pings">Pings per cycle (1–10)</Label>
                <Input
                  id="set-pings"
                  type="number"
                  min={1}
                  max={10}
                  step={1}
                  value={form.pings_per_cycle}
                  onChange={(e) =>
                    setForm({ ...form, pings_per_cycle: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-gap">Gap between pings (ms)</Label>
                <Input
                  id="set-gap"
                  type="number"
                  min={10}
                  max={5000}
                  step={10}
                  value={form.ping_gap_ms}
                  onChange={(e) =>
                    setForm({ ...form, ping_gap_ms: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-loss">Packet loss warn (%)</Label>
                <Input
                  id="set-loss"
                  type="number"
                  min={0}
                  max={100}
                  value={form.loss_warn_pct}
                  onChange={(e) =>
                    setForm({ ...form, loss_warn_pct: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-jitter">Jitter warn (ms)</Label>
                <Input
                  id="set-jitter"
                  type="number"
                  min={0}
                  value={form.jitter_warn_ms}
                  onChange={(e) =>
                    setForm({ ...form, jitter_warn_ms: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Probing: every cycle each device gets this many pings, this far
              apart. From them come its packet loss and its jitter, and a
              device at or above either threshold counts as degraded. The pings
              have to fit in the poll interval: pings × gap + the ping timeout
              may take up at most 80% of it. With 1 ping per cycle a device is
              judged on reachability and latency alone, as before.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div className="flex items-center gap-2 pt-6">
                <input
                  id="set-anomaly-enabled"
                  type="checkbox"
                  className="h-4 w-4"
                  checked={form.anomaly_enabled}
                  onChange={(e) =>
                    setForm({ ...form, anomaly_enabled: e.target.checked })
                  }
                />
                <Label htmlFor="set-anomaly-enabled">Anomaly detection</Label>
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-anomaly-detector">Detector</Label>
                <Select
                  value={form.anomaly_detector}
                  onValueChange={(next) =>
                    setForm({
                      ...form,
                      anomaly_detector: next as AppSettingsOut['anomaly_detector'],
                    })
                  }
                >
                  <SelectTrigger
                    id="set-anomaly-detector"
                    data-testid="anomaly-detector"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ewma">EWMA (frozen baseline)</SelectItem>
                    <SelectItem value="rolling">Rolling z-score</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-anomaly-k">Threshold k (1–10)</Label>
                <Input
                  id="set-anomaly-k"
                  type="number"
                  min={1}
                  max={10}
                  step={0.5}
                  value={form.anomaly_k}
                  onChange={(e) =>
                    setForm({ ...form, anomaly_k: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-anomaly-m">Readings in a row m (1–20)</Label>
                <Input
                  id="set-anomaly-m"
                  type="number"
                  min={1}
                  max={20}
                  step={1}
                  value={form.anomaly_m}
                  onChange={(e) =>
                    setForm({ ...form, anomaly_m: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="set-anomaly-alpha">
                  EWMA alpha (0.01–0.5)
                </Label>
                <Input
                  id="set-anomaly-alpha"
                  type="number"
                  min={0.01}
                  max={0.5}
                  step={0.01}
                  value={form.anomaly_alpha}
                  onChange={(e) =>
                    setForm({ ...form, anomaly_alpha: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="set-anomaly-window">
                  Rolling window (30–1000)
                </Label>
                <Input
                  id="set-anomaly-window"
                  type="number"
                  min={30}
                  max={1000}
                  step={1}
                  value={form.anomaly_window}
                  onChange={(e) =>
                    setForm({ ...form, anomaly_window: e.target.value })
                  }
                  required
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Anomaly detection learns what is normal for each device and
              marks latency or packet loss that is k standard deviations above
              it for m readings in a row. It is advisory: it adds a badge and
              chart markers, and never changes a status or opens an incident.
              Alpha only matters to the EWMA detector and the window only to
              the rolling one. Changing any of these starts every detector
              afresh (30 readings of warm-up). The EWMA detector also starts
              afresh by itself once a level has stayed for 360 readings: by
              then it is the new normal.
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