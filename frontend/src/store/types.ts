// Intent state type definitions matching backend models
export type IntentKey = 'I_tel' | 'I_anl' | 'I_api'
export type IntentState = 'initializing' | 'active' | 'drifting' | 'remediating' | 'violated' | 'failed'
export type DriftSeverity = 'nominal' | 'warning' | 'drift' | 'critical'
export type SystemHealth = 'NOMINAL' | 'WARNING' | 'DEGRADED' | 'CRITICAL'

export interface IntentRecord {
  intent: IntentKey
  state: IntentState
  remediation_attempts: number
  active_drift_count: number
  last_updated: number
  history: { from: IntentState; at: number; reason: string }[]
}

export interface Snapshot {
  timestamp: number
  elapsed_ms: number
  system_health: SystemHealth
  intents: Record<IntentKey, IntentRecord>
  drift_events: number
  causal_links: number
  most_severe: DriftSeverity
  log: string[]
}

export interface DriftAlert {
  most_severe: DriftSeverity
  system_health: SystemHealth
  log: string[]
}

export interface CompiledIntent {
  intent_id: string
  decision: 'proceed' | 'defer' | 'reject' | 'overclose_risk'
  gap_vector: {
    c_sem: number
    c_evid: number
    c_proc: number
    c_inst: number
    l2_norm: number
    dominant_gap: string
  }
  compilation_time_ms: number
  notes: string[]
}
