import React from 'react'
import { clsx } from 'clsx'

interface LogEntry {
  text: string
  ts: number
}

interface Props {
  entries: LogEntry[]
}

export function EventLog({ entries }: Props) {
  const containerRef = React.useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom
  React.useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [entries])

  const getColor = (text: string): string => {
    if (text.includes('VIOLATED') || text.includes('SLA')) return 'text-red-400'
    if (text.includes('CRITICAL') || text.includes('🔴')) return 'text-red-300'
    if (text.includes('Remediat') || text.includes('🔧')) return 'text-blue-400'
    if (text.includes('✅') || text.includes('resolved')) return 'text-emerald-400'
    if (text.includes('causal') || text.includes('⛓️')) return 'text-purple-400'
    if (text.includes('⚠️') || text.includes('drift')) return 'text-yellow-400'
    return 'text-gray-400'
  }

  return (
    <div className="card flex flex-col h-full">
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">
        📋 Event Log
      </p>
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto space-y-1 min-h-[200px] max-h-[320px]"
      >
        {entries.length === 0 ? (
          <p className="text-gray-600 text-xs italic">Waiting for events...</p>
        ) : (
          entries.map((entry, i) => (
            <div key={i} className="flex gap-2 text-xs font-mono">
              <span className="text-gray-600 shrink-0">
                {new Date(entry.ts * 1000).toLocaleTimeString()}
              </span>
              <span className={clsx('flex-1', getColor(entry.text))}>{entry.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
