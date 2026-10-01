import React from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'

export interface KPIPoint {
  t: string
  I_tel?: number
  I_anl?: number
  I_api?: number
}

interface Props {
  data: KPIPoint[]
  kpiName: string
  thresholds?: { I_tel?: number; I_anl?: number; I_api?: number }
}

const COLORS = {
  I_tel: '#34d399',   // emerald
  I_anl: '#818cf8',   // indigo
  I_api: '#f59e0b',   // amber
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 text-xs shadow-xl">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color }} className="font-mono">
          {p.dataKey}: {Number(p.value).toFixed(1)}
        </p>
      ))}
    </div>
  )
}

export function KPIChart({ data, kpiName, thresholds }: Props) {
  return (
    <div className="card">
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">
        📈 {kpiName}
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fill: '#6b7280', fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: '11px', paddingTop: '8px' }}
            formatter={(v) => <span style={{ color: COLORS[v as keyof typeof COLORS] }}>{v}</span>}
          />
          {thresholds?.I_tel && (
            <ReferenceLine y={thresholds.I_tel} stroke={COLORS.I_tel} strokeDasharray="4 4" strokeOpacity={0.5} />
          )}
          {thresholds?.I_anl && (
            <ReferenceLine y={thresholds.I_anl} stroke={COLORS.I_anl} strokeDasharray="4 4" strokeOpacity={0.5} />
          )}
          {thresholds?.I_api && (
            <ReferenceLine y={thresholds.I_api} stroke={COLORS.I_api} strokeDasharray="4 4" strokeOpacity={0.5} />
          )}
          {(['I_tel', 'I_anl', 'I_api'] as const).map((key) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={COLORS[key]}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
