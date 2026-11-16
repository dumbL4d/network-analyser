import type { DeviceAnomaly } from '@/types/device'

/** How each metric an anomaly detector watches is written out. */
const METRICS: Record<string, { label: string; unit: string }> = {
  latency: { label: 'latency', unit: 'ms' },
  loss: { label: 'packet loss', unit: '%' },
}

/**
 * What a device's anomaly says, in words: "Unusual latency: 60.5 ms, usually
 * about 10.5 ms". One sentence per metric that is out of the ordinary.
 */
export function describeAnomaly(anomaly: DeviceAnomaly): string {
  return Object.entries(anomaly)
    .map(([metric, finding]) => {
      const { label, unit } = METRICS[metric] ?? { label: metric, unit: '' }
      return `Unusual ${label}: ${finding.value.toFixed(1)} ${unit}, usually about ${finding.expected.toFixed(1)} ${unit}`
    })
    .join('; ')
}
