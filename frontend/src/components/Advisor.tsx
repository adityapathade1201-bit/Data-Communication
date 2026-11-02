import { useState } from 'react'
import { post } from '../api'
import type { AdvisorResult, Applied, SimConfig } from '../types'
import { fmt } from '../lib'
import { Section } from './fields'

const DOT: Record<string, string> = { ok: 'bg-ok', info: 'bg-pulse', warn: 'bg-warn', bad: 'bg-bad' }
const ROWS: [string, string, string, boolean][] = [
  ['throughput_mbps', 'Throughput', 'Mbps', true], ['loss_pct', 'Loss', '%', false], ['delay_avg_ms', 'Avg delay', 'ms', false],
  ['delay_p95_ms', 'p95 delay', 'ms', false], ['jain', 'Fairness', '', true],
]

export default function Advisor({ config, onAdopt }: { config: SimConfig; onAdopt: (c: SimConfig) => void }) {
  const [res, setRes] = useState<AdvisorResult | null>(null)
  const [applied, setApplied] = useState<Applied | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (apply?: string) => {
    setBusy(apply ?? 'analyze'); setError(null)
    try {
      const r = await post<AdvisorResult>('/api/advisor', { config, apply: apply ?? null })
      setRes(r)
      setApplied(r.applied ?? null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Section title="Congestion advisor" right={
      <button className="btn btn-primary btn-sm" disabled={busy !== null || config.flows.length === 0} onClick={() => run()}>
        {busy === 'analyze' ? 'Analyzing…' : res ? 'Re-analyze' : 'Analyze'}
      </button>}>
      {error && <p className="mb-2 rounded-md bg-bad/10 px-2 py-1.5 text-sm text-bad">{error}</p>}
      {!res && !error && <p className="text-sm text-slate-400">Runs the current scenario, explains <em>why</em> congestion happened from the recorded metrics, and suggests fixes you can test with one click. Rule-based, no AI model involved.</p>}
      {res && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-100">{res.advice.headline}</h3>
          <ul className="space-y-1.5 text-[13px]">
            {res.advice.diagnosis.map((d, i) => (
              <li key={i} className="flex gap-2"><span className={`mt-1.5 h-2 w-2 flex-none rounded-full ${DOT[d.severity]}`} /><span>{d.text}</span></li>
            ))}
          </ul>
          {res.advice.suggestions.map((s) => (
            <div key={s.id} className="rounded-lg border border-ink-500 bg-ink-900/60 p-2.5">
              <div className="text-sm font-medium text-slate-100">{s.title}</div>
              <p className="mt-0.5 text-[12px] text-slate-400">{s.why}</p>
              <p className="mt-0.5 text-[12px] text-slate-500">Expected: {s.expected}</p>
              <button className="btn btn-sm mt-2" disabled={busy !== null} onClick={() => run(s.id)}>
                {busy === s.id ? 'Re-running…' : 'Apply suggestion and re-run'}
              </button>
            </div>
          ))}
          {applied && (
            <div className={`rounded-lg border p-2.5 ${applied.improved ? 'border-ok/50 bg-ok/5' : 'border-warn/50 bg-warn/5'}`}>
              <div className="text-sm font-semibold">{applied.improved ? '✅ Measured improvement' : '⚠️ No clear improvement'} — {applied.suggestion.title}</div>
              <p className="mt-1 text-[12px] text-slate-300">{applied.text}</p>
              <table className="mt-2 w-full text-[12px]">
                <thead><tr className="text-left text-slate-500"><th className="font-normal">Metric</th><th className="text-right font-normal">Before</th><th className="text-right font-normal">After</th><th className="text-right font-normal">Δ</th></tr></thead>
                <tbody>
                  {ROWS.map(([k, name, unit, higher]) => {
                    const d = applied.delta_pct[k]
                    const good = d === null || d === undefined || Math.abs(d) < 1 ? null : higher ? d > 0 : d < 0
                    return (
                      <tr key={k} className="border-t border-ink-600/60 font-mono">
                        <td className="py-1 font-sans text-slate-300">{name}</td>
                        <td className="text-right">{fmt(applied.before[k])}{unit && ` ${unit}`}</td>
                        <td className="text-right">{fmt(applied.after[k])}{unit && ` ${unit}`}</td>
                        <td className={`text-right ${good === null ? 'text-slate-500' : good ? 'text-ok' : 'text-bad'}`}>{d === null || d === undefined ? '–' : `${d > 0 ? '+' : ''}${d.toFixed(0)}%`}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <button className="btn btn-sm mt-2" onClick={() => onAdopt(applied.config)}>Load this fixed scenario into the simulator</button>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}
