import type { IncidentOut } from '@/types/incident'

/** An extra link between two devices (GET /api/links row). Undirected. */
export interface LinkOut {
  id: number
  /** Always the smaller of the two device ids. */
  device_a_id: string
  device_b_id: string
}

/** A single point of failure (GET /api/analysis/spof row). */
export interface SpofOut {
  device_id: string
  /** How many other devices lose every path to a root if this one fails. */
  blast_radius: number
  cut_off_device_ids: string[]
}

/** POST /api/analysis/what-if response. */
export interface WhatIfResult {
  /** The incidents the analysis would report: same shape as the live list. */
  incidents: IncidentOut[]
  /** Devices that did not fail themselves but would be cut off. */
  unreachable_device_ids: string[]
  total_blast_radius: number
}
