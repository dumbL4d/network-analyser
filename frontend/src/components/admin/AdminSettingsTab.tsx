import {
  Activity,
  Gauge,
  Radar,
  SlidersHorizontal,
  TimerReset,
} from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
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

function SectionHeader({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof Activity
  title: string
  description: string
}) {
  return (
    <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div>
        <p className="text-[13px] font-semibold text-slate-900">{title}</p>
        <p className="mt-0.5 max-w-3xl text-[11px] leading-relaxed text-slate-500">
          {description}
        </p>
      </div>
    </div>
  )
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string
  htmlFor: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint !== undefined && (
        <p className="text-[10px] leading-snug text-slate-400">{hint}</p>
      )}
    </div>
  )
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
      <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-5 text-[12px] text-rose-700">
        Failed to load settings: {loadError}
      </div>
    )
  }

  if (form === null) {
    return (
      <Card className="p-10 text-center text-[12px] text-slate-500">
        Loading settings…
      </Card>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Card className="overflow-hidden">
        <SectionHeader
          icon={SlidersHorizontal}
          title="General"
          description="Identity and cadence of the monitoring loop. Changes apply on the poll loop's next cycle — no restart needed."
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Site name" htmlFor="set-site">
            <Input
              id="set-site"
              value={form.site_name}
              onChange={(e) => setForm({ ...form, site_name: e.target.value })}
              required
            />
          </Field>
          <Field
            label="Poll interval (seconds, min 5)"
            htmlFor="set-poll"
            hint="The original tool's minimum poll interval is 5 seconds."
          >
            <Input
              id="set-poll"
              type="number"
              step="0.5"
              min={5}
              value={form.poll_interval_seconds}
              onChange={(e) =>
                setForm({ ...form, poll_interval_seconds: e.target.value })
              }
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field
            label="Flap threshold"
            htmlFor="set-flap"
            hint="Confirmed status changes that mark a device as flapping."
          >
            <Input
              id="set-flap"
              type="number"
              min={1}
              value={form.flap_threshold}
              onChange={(e) =>
                setForm({ ...form, flap_threshold: e.target.value })
              }
              className="mono text-[12px]"
              required
            />
          </Field>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <SectionHeader
          icon={Gauge}
          title="Health thresholds"
          description="Where a reading stops being healthy and starts counting against a device."
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <Field
            label="Latency warn (ms, must be < crit)"
            htmlFor="set-warn"
          >
            <Input
              id="set-warn"
              type="number"
              min={0}
              value={form.latency_warn_ms}
              onChange={(e) =>
                setForm({ ...form, latency_warn_ms: e.target.value })
              }
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Latency crit (ms)" htmlFor="set-crit">
            <Input
              id="set-crit"
              type="number"
              min={0}
              value={form.latency_crit_ms}
              onChange={(e) =>
                setForm({ ...form, latency_crit_ms: e.target.value })
              }
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Packet loss warn (%)" htmlFor="set-loss">
            <Input
              id="set-loss"
              type="number"
              min={0}
              max={100}
              value={form.loss_warn_pct}
              onChange={(e) =>
                setForm({ ...form, loss_warn_pct: e.target.value })
              }
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Jitter warn (ms)" htmlFor="set-jitter">
            <Input
              id="set-jitter"
              type="number"
              min={0}
              value={form.jitter_warn_ms}
              onChange={(e) =>
                setForm({ ...form, jitter_warn_ms: e.target.value })
              }
              className="mono text-[12px]"
              required
            />
          </Field>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <SectionHeader
          icon={TimerReset}
          title="Debouncing"
          description="A device's status gets worse only after this many bad results in a row, and better only after this many good polls in a row. Set both to 1 to switch debouncing off."
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Failure threshold (results, 1–10)" htmlFor="set-failure">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Recovery threshold (polls, 1–10)" htmlFor="set-recovery">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <p className="text-[11px] leading-relaxed text-slate-500 sm:col-span-2 lg:col-span-2">
            After a bad result the device is probed again a second later,
            without waiting for the next poll.
          </p>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <SectionHeader
          icon={Radar}
          title="Probing"
          description="Every cycle each device gets this many pings, sent this far apart whether or not the one before was answered. From them come its packet loss and jitter."
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Pings per cycle (1–10)" htmlFor="set-pings">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Gap between pings (ms)" htmlFor="set-gap">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <p className="text-[11px] leading-relaxed text-slate-500 sm:col-span-2 lg:col-span-2">
            A device at or above either the loss or jitter threshold counts as
            degraded. The pings have to fit in the poll interval: pings × gap
            + the ping timeout may take up at most 80% of it. With 1 ping per
            cycle a device is judged on reachability and latency alone.
          </p>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <SectionHeader
          icon={Activity}
          title="Anomaly detection"
          description="Learns what is normal for each device and marks latency or packet loss that is k standard deviations above it for m readings in a row. Advisory only: it adds a badge and chart markers, and never changes a status or opens an incident."
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <label
            htmlFor="set-anomaly-enabled"
            className="flex items-center gap-2.5 rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5 sm:col-span-2"
          >
            <input
              id="set-anomaly-enabled"
              type="checkbox"
              className="h-4 w-4 rounded border-slate-300 accent-blue-600"
              checked={form.anomaly_enabled}
              onChange={(e) =>
                setForm({ ...form, anomaly_enabled: e.target.checked })
              }
            />
            <span className="text-[12px] font-medium text-slate-700">
              Anomaly detection
            </span>
            <span className="ml-auto text-[10px] uppercase tracking-[0.1em] text-slate-400">
              {form.anomaly_enabled ? 'Enabled' : 'Off'}
            </span>
          </label>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="set-anomaly-detector">Detector</Label>
            <Select
              value={form.anomaly_detector}
              onValueChange={(next) =>
                setForm({
                  ...form,
                  anomaly_detector:
                    next as AppSettingsOut['anomaly_detector'],
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
          <Field label="Threshold k (1–10)" htmlFor="set-anomaly-k">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Readings in a row m (1–20)" htmlFor="set-anomaly-m">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="EWMA alpha (0.01–0.5)" htmlFor="set-anomaly-alpha">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <Field label="Rolling window (30–1000)" htmlFor="set-anomaly-window">
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
              className="mono text-[12px]"
              required
            />
          </Field>
          <p className="text-[11px] leading-relaxed text-slate-500 sm:col-span-2 lg:col-span-4">
            Alpha only matters to the EWMA detector and the window only to the
            rolling one. Changing any of these starts every detector afresh (30
            readings of warm-up). The EWMA detector also starts afresh by itself
            once a level has stayed for 360 readings: by then it is the new
            normal.
          </p>
        </div>
      </Card>

      <div className="sticky bottom-4 z-10 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/90 px-4 py-3 shadow-float backdrop-blur-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="min-h-4">
          {success !== null && (
            <p className="text-[12px] font-medium text-emerald-700">
              {success}
            </p>
          )}
          {error !== null && (
            <p data-testid="settings-error" className="text-[12px] text-rose-700">
              {error}
            </p>
          )}
          {success === null && error === null && (
            <p className="text-[11px] text-slate-400">
              All values are validated server-side. Invalid combinations are
              rejected with a message.
            </p>
          )}
        </div>
        <Button type="submit" disabled={saving} className="shrink-0">
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
      </div>
    </form>
  )
}
