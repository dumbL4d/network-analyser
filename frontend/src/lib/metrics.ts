import type { HistorySampleOut } from '@/types/device'

/**
 * Median latency in ms over a device's non-null history samples, or `null`
 * when there are no non-null samples to summarize.
 */
export function computeMedianLatency(
  samples: HistorySampleOut[],
): number | null {
  const values = samples
    .map((sample) => sample.latency_ms)
    .filter((value): value is number => value !== null)
    .sort((a, b) => a - b)

  if (values.length === 0) return null

  const middle = Math.floor(values.length / 2)
  if (values.length % 2 === 1) return values[middle]
  return (values[middle - 1] + values[middle]) / 2
}

/**
 * Reachability ratio as a percentage (0-100): the share of history samples
 * where the device answered (non-null latency). Empty sample windows report 0
 * so down/unknown periods are never masked.
 */
export function computeReachabilityRatio(samples: HistorySampleOut[]): number {
  if (samples.length === 0) return 0
  const reachable = samples.filter(
    (sample) => sample.latency_ms !== null,
  ).length
  return Math.round((reachable / samples.length) * 100)
}