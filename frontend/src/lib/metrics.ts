import type { HistoryPoint } from '@/types/device'

/**
 * Median latency in ms over the points that have a latency, or `null` when
 * none has. For bucketed history this is the median of the bucket averages.
 */
export function computeMedianLatency(
  points: Pick<HistoryPoint, 'latency_ms'>[],
): number | null {
  const values = points
    .map((point) => point.latency_ms)
    .filter((value): value is number => value !== null)
    .sort((a, b) => a - b)

  if (values.length === 0) return null

  const middle = Math.floor(values.length / 2)
  if (values.length % 2 === 1) return values[middle]
  return (values[middle - 1] + values[middle]) / 2
}

/** Mean of the values that are there, or `null` when none is. */
export function computeMean(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null)
  if (present.length === 0) return null
  return present.reduce((sum, value) => sum + value, 0) / present.length
}

/** The highest of the values that are there, or `null` when none is. */
export function computePeak(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null)
  return present.length === 0 ? null : Math.max(...present)
}

/**
 * Reachability as a percentage (0-100): the share of polls that got a reply.
 * A bucketed point stands for several polls, so the counts are used; a raw
 * reading counts as one poll. No polls at all reports 0, so down/unknown
 * periods are never masked.
 */
export function computeReachabilityRatio(
  points: Pick<HistoryPoint, 'sample_count' | 'fail_count'>[],
): number {
  const polls = points.reduce((sum, point) => sum + point.sample_count, 0)
  if (polls === 0) return 0
  const failed = points.reduce((sum, point) => sum + point.fail_count, 0)
  return Math.round(((polls - failed) / polls) * 100)
}
