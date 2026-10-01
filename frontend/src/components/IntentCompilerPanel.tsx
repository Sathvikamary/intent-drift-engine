import React from 'react'
import { clsx } from 'clsx'
import type { CompiledIntent } from '../store/types'

interface Props {
  intents: CompiledIntent[]
}

const DECISION_STYLE: Record<string, string> = {
  proceed:       'text-emerald-400 bg-emerald-900/20 border-emerald-800',
  defer:         'text-yellow-400  bg-yellow-900/20  border-yellow-800',
  reject:        'text-red-400     bg-red-900/20     border-red-800',
  overclose_risk:'text-orange-400  bg-orange-900/20  border-orange-800',
}

const GAP_COLOR = (val: number) => {
  if (val <= 0.2) return 'bg-emerald-500'
  if (val <= 0.5) return 'bg-yellow-500'
  if (val <= 0.75) return 'bg-orange-500'
  return 'bg-red-500'
}

function GapBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="mb-1">
      <div className="flex justify-between text-xs mb-0.5">
        <span className="text-gray-500">{label}</span>
        <span className="text-gray-400 font-mono">{value.toFixed(2)}</span>
      </div>
      <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-700', GAP_COLOR(value))}
          style={{ width: `${value * 100}%` }}
        />
      </div>
    </div>
  )
}

export function IntentCompilerPanel({ intents }: Props) {
  return (
    <div className="card">
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">
        ⚙️ Intent Compiler — Closure Gap Ct
      </p>
      {intents.length === 0 ? (
        <p className="text-gray-600 text-xs italic">No intents compiled yet.</p>
      ) : (
        <div className="space-y-3 max-h-[320px] overflow-y-auto">
          {[...intents].reverse().map((intent) => (
            <div key={intent.intent_id} className="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-400 font-mono">#{intent.intent_id}</span>
                <span className={clsx(
                  'text-xs px-2 py-0.5 rounded border font-semibold uppercase',
                  DECISION_STYLE[intent.decision] ?? 'text-gray-400'
                )}>
                  {intent.decision.replace('_', ' ')}
                </span>
              </div>
              <div className="mb-2">
                <GapBar label="Semantic (Csem)"      value={intent.gap_vector.c_sem} />
                <GapBar label="Evidentiary (Cevid)"  value={intent.gap_vector.c_evid} />
                <GapBar label="Procedural (Cproc)"   value={intent.gap_vector.c_proc} />
                <GapBar label="Institutional (Cinst)" value={intent.gap_vector.c_inst} />
              </div>
              <div className="flex justify-between text-xs text-gray-500">
                <span>‖Ct‖ = {intent.gap_vector.l2_norm.toFixed(3)}</span>
                <span>dominant: {intent.gap_vector.dominant_gap}</span>
                <span>{intent.compilation_time_ms.toFixed(1)}ms</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
