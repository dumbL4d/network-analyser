import { fetchDeviceHistory, fetchDeviceHistoryWindow } from '@/lib/api'
import type {
  HistoryPoint,
  HistoryRange,
  HistorySampleOut,
} from '@/types/device'

/** Choices offered by the time-range selector. */
export const RANGE_OPTIONS: { value: HistoryRange; label: string }[] = [
  { value: 'live', label: 'Live' },
  { value: '1h', label: 'Last hour' },
  { value: '6h', label: 'Last 6 hours' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
]

export interface LoadedHistory {
  points: HistoryPoint[]
  /** 'raw', or the bucket size the backend used ('1m', '5m', '30m', '2h'). */
  resolution: string
}

/** The live samples change every poll cycle; the longer ranges barely move. */
export function refreshMs(range: HistoryRange): number {
  return range === 'live' ? 10_000 : 60_000
}

/** A raw sample as a point: one poll, so min = max = the reading. */
function fromSamples(samples: HistorySampleOut[]): HistoryPoint[] {
  return samples.map((sample) => ({
    timestamp: sample.timestamp,
    latency_ms: sample.latency_ms,
    min_ms: sample.latency_ms,
    max_ms: sample.latency_ms,
    sample_count: 1,
    fail_count: sample.latency_ms === null ? 1 : 0,
    loss_pct: sample.loss_pct,
    loss_max_pct: sample.loss_pct,
    jitter_ms: sample.jitter_ms,
    jitter_max_ms: sample.jitter_ms,
  }))
}

/**
 * History of one device for a range, in one shape for every range. 'live'
 * uses the original endpoint (recent samples); the others ask for a window.
 */
export async function loadHistory(
  deviceId: string,
  range: HistoryRange,
): Promise<LoadedHistory> {
  if (range === 'live') {
    return {
      points: fromSamples(await fetchDeviceHistory(deviceId)),
      resolution: 'raw',
    }
  }
  const data = await fetchDeviceHistoryWindow(deviceId, range)
  return { points: data.points, resolution: data.resolution }
}

/** What a history chart can show. */
export type HistoryMetric = 'latency' | 'loss' | 'jitter'

interface MetricSpec {
  label: string
  unit: string
  /** The line: the reading, or the bucket's average. */
  value: (point: HistoryPoint) => number | null
  /** The shaded band of a bucket, from `low` to `high`. */
  low: (point: HistoryPoint) => number | null
  high: (point: HistoryPoint) => number | null
  /** What the band means, for the tooltip. */
  bandLabel: string
}

export const METRICS: Record<HistoryMetric, MetricSpec> = {
  latency: {
    label: 'Latency',
    unit: 'ms',
    value: (point) => point.latency_ms,
    low: (point) => point.min_ms,
    high: (point) => point.max_ms,
    bandLabel: 'min – max',
  },
  loss: {
    label: 'Packet loss',
    unit: '%',
    value: (point) => point.loss_pct,
    low: (point) => point.loss_pct,
    high: (point) => point.loss_max_pct,
    bandLabel: 'average – peak',
  },
  jitter: {
    label: 'Jitter',
    unit: 'ms',
    value: (point) => point.jitter_ms,
    low: (point) => point.jitter_ms,
    high: (point) => point.jitter_max_ms,
    bandLabel: 'average – peak',
  },
}

export interface ChartDatum {
  index: number
  timestamp: string
  /** The metric's reading (or bucket average); null when there is none. */
  value: number | null
  /** [low, high] for the shaded band; null when there is nothing to show. */
  band: [number, number] | null
  sample_count: number
  fail_count: number
}

/** Shape history points for Recharts (line = value, band = low..high). */
export function toChartData(
  points: HistoryPoint[],
  metric: HistoryMetric = 'latency',
): ChartDatum[] {
  const spec = METRICS[metric]
  return points.map((point, index) => {
    const low = spec.low(point)
    const high = spec.high(point)
    return {
      index,
      timestamp: point.timestamp,
      value: spec.value(point),
      band: low === null || high === null ? null : [low, high],
      sample_count: point.sample_count,
      fail_count: point.fail_count,
    }
  })
}

/** Axis label: time of day for the short ranges, the date for the long ones. */
export function formatTick(timestamp: string, range: HistoryRange): string {
  const date = new Date(timestamp)
  if (range === '7d' || range === '30d') {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  if (range === 'live') return date.toLocaleTimeString()
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Human wording for the resolution the backend reported. */
export function describeResolution(
  resolution: string,
  metric: HistoryMetric = 'latency',
): string {
  return resolution === 'raw'
    ? 'every poll'
    : `${resolution} buckets (average, shaded ${METRICS[metric].bandLabel.replace(/ /g, '')})`
}
