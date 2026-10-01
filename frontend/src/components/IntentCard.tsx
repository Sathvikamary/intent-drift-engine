import React from 'react'
import { clsx } from 'clsx'
import type { IntentRecord, IntentKey, IntentState } from '../store/types'

const INTENT_LABELS: Record<IntentKey, string> = {
  I_tel: 'Telemetry',
  I_anl: 'Analytics',
  I_api: 'API Gateway',
}

const INTENT_ICONS: Record<IntentKey, string> = {
  I_tel: '📡',
  I_anl: '🧠',
  I_api: '🌐',
}

const STATE_STYLES: Record<IntentState, string> = {
  initializing: 'bg-gray-800 text-gray-400 border-gray-700',
  active:       'bg-emerald-900/30 text-emerald-300 border-emerald-700',
  drifting:     'bg-yellow-900/30  text-yellow-300  border-yellow-700  animate-pulse',
  remediating:  'bg-blue-900/30    text-blue-300    border-blue-700    animate-pulse-slow',
  violated:     'bg-red-900/40     text-red-300     border-red-700     animate-pulse',
  failed:       'bg-red-950        text-red-200     border-red-900',
}

const STATE_DOT: Record<IntentState, string> = {
  initializing: 'bg-gray-500',
  active:       'bg-emerald-400',
  drifting:     'bg-yellow-400',
  remediating:  'bg-blue-400',
  violated:     'bg-red-400',
  failed:       'bg-red-600',
}

interface Props {
  intentKey: IntentKey
  record: IntentRecord
}

export function IntentCard({ intentKey, record }: Props) {
  const { state, remediation_attempts, active_drift_count, history } = record
  const lastTransition = history[history.length - 1]

  return (
    <div className={clsx('card border-2 transition-all duration-500', STATE_STYLES[state])}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{INTENT_ICONS[intentKey]}</span>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider">
              {intentKey}
            </p>
            <p className="font-bold text-sm">{INTENT_LABELS[intentKey]}</p>
          </div>
        </div>
        <div className={clsx('flex items-center gap-1.5 px-2 py-1 rounded-full border text-xs font-semibold uppercase')}>
          <div className={clsx('w-2 h-2 rounded-full', STATE_DOT[state])} />
          {state}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-black/20 rounded-lg p-2">
          <p className="text-gray-500">Active Drift Events</p>
          <p className={clsx('text-lg font-bold', active_drift_count > 0 ? 'text-yellow-400' : 'text-gray-300')}>
            {active_drift_count}
          </p>
        </div>
        <div className="bg-black/20 rounded-lg p-2">
          <p className="text-gray-500">Remediation Attempts</p>
          <p className={clsx('text-lg font-bold', remediation_attempts > 0 ? 'text-blue-400' : 'text-gray-300')}>
            {remediation_attempts}
          </p>
        </div>
      </div>

      {/* Last transition */}
      {lastTransition && (
        <div className="mt-2 text-xs text-gray-500 truncate">
          ↳ from <span className="text-gray-400">{lastTransition.from}</span>: {lastTransition.reason}
        </div>
      )}
    </div>
  )
}
