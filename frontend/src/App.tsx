import React, { useState, useCallback, useRef } from 'react'
import { useWebSocket, type WSMessage } from './hooks/useWebSocket'
import { SystemHealthBar } from './components/SystemHealthBar'
import { IntentCard } from './components/IntentCard'
import { KPIChart, type KPIPoint } from './components/KPIChart'
import { EventLog } from './components/EventLog'
import { IntentCompilerPanel } from './components/IntentCompilerPanel'
import type { Snapshot, CompiledIntent, SystemHealth, DriftSeverity, IntentKey, IntentRecord } from './store/types'

const WS_URL = `ws://${window.location.hostname}:8000/ws/kpi-stream`

const DEFAULT_INTENTS: Record<IntentKey, IntentRecord> = {
  I_tel: { intent: 'I_tel', state: 'initializing', remediation_attempts: 0, active_drift_count: 0, last_updated: 0, history: [] },
  I_anl: { intent: 'I_anl', state: 'initializing', remediation_attempts: 0, active_drift_count: 0, last_updated: 0, history: [] },
  I_api: { intent: 'I_api', state: 'initializing', remediation_attempts: 0, active_drift_count: 0, last_updated: 0, history: [] },
}

interface LogEntry { text: string; ts: number }

export default function App() {
  const [health, setHealth]           = useState<SystemHealth>('NOMINAL')
  const [severity, setSeverity]       = useState<DriftSeverity>('nominal')
  const [intents, setIntents]         = useState(DEFAULT_INTENTS)
  const [driftEvents, setDriftEvents] = useState(0)
  const [causalLinks, setCausalLinks] = useState(0)
  const [tickCount, setTickCount]     = useState(0)
  const [log, setLog]                 = useState<LogEntry[]>([])
  const [kpiData, setKpiData]         = useState<KPIPoint[]>([])
  const [compiledIntents, setCompiledIntents] = useState<CompiledIntent[]>([])
  const [compileInput, setCompileInput] = useState('')
  const [compiling, setCompiling]     = useState(false)

  const tickRef = useRef(0)

  const addLog = useCallback((entries: string[], ts: number) => {
    setLog(prev => [...prev.slice(-200), ...entries.map(text => ({ text, ts }))])
  }, [])

  const onMessage = useCallback((msg: WSMessage) => {
    if (msg.type === 'state_snapshot') {
      const snap = msg.payload as unknown as Snapshot
      setHealth(snap.system_health)
      setSeverity(snap.most_severe)
      setIntents(snap.intents as unknown as typeof DEFAULT_INTENTS)
      setDriftEvents(prev => prev + snap.drift_events)
      setCausalLinks(snap.causal_links)
      tickRef.current += 1
      setTickCount(tickRef.current)

      if (snap.log?.length) {
        addLog(snap.log, snap.timestamp)
      }

      // Append to KPI chart (simplified — tracks drift event count per tick)
      setKpiData(prev => {
        const point: KPIPoint = {
          t: new Date(snap.timestamp * 1000).toLocaleTimeString(),
          I_tel: snap.intents['I_tel']?.active_drift_count ?? 0,
          I_anl: snap.intents['I_anl']?.active_drift_count ?? 0,
          I_api: snap.intents['I_api']?.active_drift_count ?? 0,
        }
        return [...prev.slice(-60), point]
      })
    }

    if (msg.type === 'drift_alert') {
      const alert = msg.payload as { log: string[]; system_health: SystemHealth }
      addLog(alert.log ?? [], msg.ts)
    }

    if (msg.type === 'intent_compiled') {
      const compiled = msg.payload as unknown as CompiledIntent
      setCompiledIntents(prev => [...prev.slice(-20), compiled])
    }
  }, [addLog])

  const { status: wsStatus } = useWebSocket({ url: WS_URL, onMessage })

  // Manual intent compile
  const handleCompile = async () => {
    if (!compileInput.trim()) return
    setCompiling(true)
    try {
      const resp = await fetch('/api/intents/compile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intent_text: compileInput,
          role: 'network-ops',
          domain: 'api-gateway',
          required_actions: ['read_metrics'],
          closure_threshold: 0.25,
        }),
      })
      const data = await resp.json()
      setCompiledIntents(prev => [...prev.slice(-20), data])
    } catch (e) {
      addLog([`❌ Compile failed: ${e}`], Date.now() / 1000)
    } finally {
      setCompiling(false)
    }
  }

  return (
    <div className="min-h-screen p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">
            🌐 Intent Drift Engine
          </h1>
          <p className="text-xs text-gray-500">
            IBN · Real-Time Intent Assurance Dashboard
          </p>
        </div>
        <a
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-sky-500 hover:text-sky-400 border border-sky-900 hover:border-sky-700 px-3 py-1.5 rounded-lg transition-colors"
        >
          API Docs ↗
        </a>
      </div>

      {/* System Health Bar */}
      <SystemHealthBar
        health={health}
        severity={severity}
        driftEvents={driftEvents}
        causalLinks={causalLinks}
        wsStatus={wsStatus}
        tickCount={tickCount}
      />

      {/* Intent State Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(Object.keys(DEFAULT_INTENTS) as IntentKey[]).map(key => (
          <IntentCard key={key} intentKey={key} record={intents[key]} />
        ))}
      </div>

      {/* KPI Chart + Event Log */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <KPIChart
          data={kpiData}
          kpiName="Active Drift Events per Intent (real-time)"
          thresholds={{ I_tel: 2, I_anl: 2, I_api: 2 }}
        />
        <EventLog entries={log} />
      </div>

      {/* Intent Compiler + Input */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <IntentCompilerPanel intents={compiledIntents} />

        <div className="card space-y-3">
          <p className="text-xs text-gray-500 uppercase tracking-wider">
            ✍️ Compile Intent
          </p>
          <textarea
            className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm text-gray-200 resize-none focus:outline-none focus:border-sky-700 font-mono"
            rows={4}
            placeholder="Ensure API gateway p99 latency < 50ms with SLA = 99.9%..."
            value={compileInput}
            onChange={e => setCompileInput(e.target.value)}
          />
          <button
            onClick={handleCompile}
            disabled={compiling || !compileInput.trim()}
            className="w-full py-2 px-4 bg-sky-700 hover:bg-sky-600 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg text-sm font-semibold transition-colors"
          >
            {compiling ? '⚙️ Compiling...' : '⚡ Compile Intent'}
          </button>
          <p className="text-xs text-gray-600">
            Connect your simulation: <code className="text-gray-500">python scripts/simulate_cascade.py</code>
          </p>
        </div>
      </div>

      {/* Causal chain diagram (static for now) */}
      <div className="card">
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">
          ⛓️ Causal Dependency Chain — SCM
        </p>
        <div className="flex items-center justify-center gap-2 flex-wrap text-sm">
          {(['I_tel', 'I_anl', 'I_api'] as IntentKey[]).map((key, i) => {
            const rec = intents[key]
            const stateColor = {
              active:      'border-emerald-600 text-emerald-300',
              drifting:    'border-yellow-600  text-yellow-300',
              remediating: 'border-blue-600    text-blue-300',
              violated:    'border-red-600     text-red-300',
              failed:      'border-red-900     text-red-400',
              initializing:'border-gray-700    text-gray-400',
            }[rec.state] ?? 'border-gray-700 text-gray-400'

            return (
              <React.Fragment key={key}>
                <div className={`border-2 rounded-xl px-4 py-3 text-center min-w-[120px] transition-all duration-500 ${stateColor}`}>
                  <p className="text-xs text-gray-500">{key}</p>
                  <p className="font-bold">{['Telemetry', 'Analytics', 'API Gateway'][i]}</p>
                  <p className="text-xs mt-1 uppercase">{rec.state}</p>
                </div>
                {i < 2 && (
                  <div className="text-gray-600 text-lg font-bold">⟶</div>
                )}
              </React.Fragment>
            )
          })}
        </div>
        <p className="text-center text-xs text-gray-600 mt-3">
          Queue backpressure (I_tel) → Throughput drop (I_anl) → p99 violation (I_api)
        </p>
      </div>
    </div>
  )
}
