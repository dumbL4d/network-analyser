/**
 * Why a simulated device is broken:
 * failed (an admin failed it), cut_off (nothing leads to it any more),
 * flapping (being switched off and on), degraded (slowed down), leftover
 * (broken, but not by this backend process: from before a restart).
 */
export type ChaosFaultKind =
  | 'failed'
  | 'cut_off'
  | 'flapping'
  | 'degraded'
  | 'leftover'

export interface ChaosFault {
  device_id: string
  kind: ChaosFaultKind
  detail: string
}

export interface ChaosScenario {
  name: string
  title: string
  description: string
}

/** GET /api/chaos/state, and the answer of every chaos action. */
export interface ChaosState {
  faults: ChaosFault[]
  scenarios: ChaosScenario[]
  /** Devices that have a simulated container, i.e. can be broken. */
  controllable_device_ids: string[]
}
