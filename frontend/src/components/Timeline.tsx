import type { Marker } from '../types'

const GLYPH: Record<string, string> = { link_failure: '✕', burst: '⚡', link_restore: '✓', burst_end: '•' }
const COLOR: Record<string, string> = { link_failure: '#f87171', burst: '#fbbf24', link_restore: '#34d399', burst_end: '#94a3b8' }

interface Props {
  duration: number
  position: number // seconds
  markers: Marker[]
  scrubbable: boolean
  onSeek: (t: number) => void
}

export default function Timeline({ duration, position, markers, scrubbable, onSeek }: Props) {
  const pct = Math.min(100, Math.max(0, (position / Math.max(duration, 0.001)) * 100))
  return (
    <div className="mt-2">
      <div className="relative h-7">
        <div className="absolute inset-x-0 top-3 h-1.5 rounded-full bg-ink-600" />
        <div className="absolute left-0 top-3 h-1.5 rounded-full bg-pulse" style={{ width: `${pct}%` }} />
        {markers.map((m, i) => (
          <div key={i} title={`${m.t.toFixed(1)}s — ${m.label}`} className="absolute -translate-x-1/2 text-[11px] leading-none"
            style={{ left: `${(m.t / Math.max(duration, 0.001)) * 100}%`, top: 0, color: COLOR[m.type] ?? '#94a3b8' }}>
            {GLYPH[m.type] ?? '•'}
          </div>
        ))}
        {scrubbable && (
          <input type="range" min={0} max={duration} step={0.05} value={position} aria-label="Replay position"
            onChange={(e) => onSeek(parseFloat(e.target.value))}
            className="absolute inset-x-0 top-1.5 h-5 w-full cursor-pointer opacity-0" />
        )}
      </div>
      <div className="flex justify-between font-mono text-[11px] text-slate-500">
        <span>{position.toFixed(1)}s</span>
        <span>{duration.toFixed(0)}s</span>
      </div>
    </div>
  )
}
