import React from 'react'
import { clsx } from 'clsx'
import type { SystemHealth, DriftSeverity } from '../store/types'

const HEALTH_CONFIG: Record<SystemHealth, { label: string; cls: string; icon: string }> = {
  NOMINAL:  { label: 'Nominal',  cls: 'badge-nominal',  icon: '✅' },
  WARNING:  { label: 'Warning',  cls: 'badge-warning',  icon: '⚠️' },
  DEGRADED: { label: 'Degraded', cls: 'badge-degraded', icon: '🟣' },
  CRITICAL: { label: 'Critical', cls: 'badge-critical', icon: '🔴' },
}

const SEVERITY_CONFIG: Record<DriftSeverity, { cls: string }> = {
  nominal:  { cls: 'text-emerald-400' },
  warning:  { cls: 'text-yellow-400' },
  drift:    { cls: 'text-orange-400' },
  critical: { cls: 'text-red-400 animate-pulse' },
}

interface Props {
  health: SystemHealth
  severity: DriftSeverity
  driftEvents: number
  causalLinks: number
  wsStatus: 'connecting' | 'open' | 'closed' | 'error'
  tickCount: number
}

export function SystemHealthBar({ health, severity, driftEvents, causalLinks, wsStatus, tickCount }: Props) {
  const hcfg = HEALTH_CONFIG[health]
  const scfg = SEVERITY_CONFIG[severity]

  const wsColor = {
    connecting: 'bg-yellow-500',
    open:       'bg-emerald-500',
    closed:     'bg-gray-500',
    error:      'bg-red-500',
  }[wsStatus]

  return (
    <div className="card flex flex-wrap items-center justify-between gap-4">
      {/* System Health */}
      <div className="flex items-center gap-3">
        <span className="text-2xl">{hcfg.icon}</span>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider">System Health</p>
          <span className={clsx('px-3 py-1 rounded-full text-sm font-bold border', hcfg.cls)}>
            {hcfg.label}
          </span>
        </div>
      </div>

      {/* Most severe drift */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider">Worst Drift</p>
        <p className={clsx('text-lg font-bold uppercase', scfg.cls)}>{severity}</p>
      </div>

      {/* Stats */}
      <div className="flex gap-6">
        <div className="text-center">
          <p className="text-xs text-gray-500">Drift Events</p>
          <p className="text-xl font-bold text-yellow-400">{driftEvents}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-500">Causal Links</p>
          <p className="text-xl font-bold text-purple-400">{causalLinks}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-500">Ticks</p>
          <p className="text-xl font-bold text-gray-300">{tickCount}</p>
        </div>
      </div>

      {/* WS status */}
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <div className={clsx('w-2 h-2 rounded-full', wsColor, wsStatus === 'open' && 'animate-pulse')} />
        WS {wsStatus}
      </div>
    </div>
  )
}
