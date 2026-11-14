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

export interface ChartDatum {
  index: number
  timestamp: string
  latency_ms: number | null
  /** [min, max] for the shaded band; null when nothing replied. */
  band: [number, number] | null
  sample_count: number
  fail_count: number
}

/** Shape history points for Recharts (line = latency_ms, band = min..max). */
export function toChartData(points: HistoryPoint[]): ChartDatum[] {
  return points.map((point, index) => ({
    index,
    timestamp: point.timestamp,
    latency_ms: point.latency_ms,
    band:
      point.min_ms === null || point.max_ms === null
        ? null
        : [point.min_ms, point.max_ms],
    sample_count: point.sample_count,
    fail_count: point.fail_count,
  }))
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
export function describeResolution(resolution: string): string {
  return resolution === 'raw'
    ? 'every poll'
    : `${resolution} buckets (average, shaded min–max)`
}
