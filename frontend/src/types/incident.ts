import type { DeviceOut } from './device'

export type IncidentCategory = 'root_cause' | 'collateral'

/** A single unhealthy device, classified against the device tree. */
export interface IncidentOut {
  device: DeviceOut
  status: string
  latency_ms: number | null
  category: IncidentCategory
  /** Only set on root causes: the concrete descendants currently affected. */
  downstream_affected: DeviceOut[]
}

/** Guided-fix steps for one device type + state combination. */
export interface PlaybookOut {
  device_type: string
  state: string
  steps: string[]
}