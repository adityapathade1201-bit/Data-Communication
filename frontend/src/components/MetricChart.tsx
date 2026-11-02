import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Marker } from '../types'

export interface Series { key: string; name: string; color: string; dash?: string; width?: number }
export type Row = Record<string, number | null | undefined>

const MARKER_COLOR: Record<string, string> = {
  link_failure: '#f87171', burst: '#fbbf24', link_restore: '#34d399', burst_end: '#94a3b8',
}
const MARKER_GLYPH: Record<string, string> = { link_failure: '✕', burst: '⚡', link_restore: '✓', burst_end: '·' }

interface Props {
  title: string
  unit?: string
  data: Row[]
  series: Series[]
  markers?: Marker[]
  duration: number
  height?: number
  yDomain?: [number | 'auto' | 'dataMin', number | 'auto' | 'dataMax']
  note?: string
}

export default function MetricChart({ title, unit, data, series, markers = [], duration, height = 190, yDomain, note }: Props) {
  return (
    <div className="card p-0">
      <div className="card-h">
        <span>{title}</span>
        <span className="font-mono normal-case tracking-normal text-slate-500">{unit}</span>
      </div>
      <div style={{ height }} className="px-1 pb-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 14, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="#1f2c44" strokeDasharray="3 4" />
            <XAxis dataKey="t" type="number" domain={[0, Math.max(duration, 1)]} tick={{ fill: '#8aa0bf', fontSize: 11 }}
              tickFormatter={(v: number) => `${Math.round(v * 10) / 10}s`} stroke="#2e4268" allowDataOverflow />
            <YAxis tick={{ fill: '#8aa0bf', fontSize: 11 }} stroke="#2e4268" domain={yDomain ?? [0, 'auto']} width={46} />
            <Tooltip
              contentStyle={{ background: '#0b1220', border: '1px solid #2e4268', borderRadius: 8, fontSize: 12 }}
              labelFormatter={(v) => `t = ${Number(v).toFixed(2)} s`}
              formatter={(v) => (typeof v === 'number' ? v.toFixed(2) : String(v))}
            />
            {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />}
            {markers.filter((m) => m.type !== 'burst_end').map((m, i) => (
              <ReferenceLine key={`${m.type}-${i}`} x={m.t} stroke={MARKER_COLOR[m.type] ?? '#94a3b8'} strokeDasharray="4 3"
                label={{ value: MARKER_GLYPH[m.type] ?? '•', fill: MARKER_COLOR[m.type] ?? '#94a3b8', fontSize: 12, position: 'top' }} />
            ))}
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={s.width ?? 2}
                strokeDasharray={s.dash} dot={false} isAnimationActive={false} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {note && <div className="px-3.5 pb-2.5 text-[11px] text-slate-500">{note}</div>}
    </div>
  )
}
