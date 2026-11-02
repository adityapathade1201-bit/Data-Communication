import { useMemo, useState } from 'react'
import { post } from '../api'
import type { ExperimentsResult, Preset, SimConfig } from '../types'
import { EXP_COLORS, fmt } from '../lib'
import MetricChart from './MetricChart'
import type { Row, Series } from './MetricChart'

interface Props { presets: Preset[]; current: SimConfig }

const CHART_DEFS: { title: string; unit: string; pick: (s: ExperimentsResult['experiments'][number]['samples'][number]) => number | null }[] = [
  { title: 'Total throughput', unit: 'Mbps', pick: (s) => s.global.throughput_mbps },
  { title: 'Average delay', unit: 'ms', pick: (s) => s.global.delay_avg_ms },
  { title: 'Packet loss', unit: '%', pick: (s) => s.global.loss_pct },
  { title: 'Bottleneck queue length', unit: 'packets', pick: () => null },
]

export default function ExperimentsPage({ presets, current }: Props) {
  const [source, setSource] = useState('three-sender')
  const [res, setRes] = useState<ExperimentsResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setBusy(true); setError(null)
    try {
      const body = source === 'current' ? { config: current } : { preset: source }
      setRes(await post<ExperimentsResult>('/api/experiments/run', body))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setRes(null)
    } finally {
      setBusy(false)
    }
  }

  const ids = res?.experiments.map((e) => e.id) ?? []
  const duration = res?.experiments[0]?.summary.duration_s ?? 20
  const series: Series[] = ids.map((id) => ({ key: id, name: `${id} · ${res?.experiments.find((e) => e.id === id)?.name}`, color: EXP_COLORS[id] ?? '#7c9cff' }))

  const charts = useMemo(() => {
    if (!res) return []
    const port = res.experiments[0].summary.bottleneck?.port
    return CHART_DEFS.map((def, ci) => {
      const n = Math.max(...res.experiments.map((e) => e.samples.length))
      const rows: Row[] = []
      for (let i = 0; i < n; i++) {
        const row: Row = { t: res.experiments[0].samples[i]?.t }
        for (const e of res.experiments) {
          const s = e.samples[i]
          row[e.id] = s ? (ci === 3 ? (port ? s.links[port]?.qlen ?? null : null) : def.pick(s)) : null
        }
        rows.push(row)
      }
      return { ...def, rows }
    })
  }, [res])

  const dirHint = (d: string) => (d === 'higher' ? '↑ better' : d === 'lower' ? '↓ better' : '')
  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[16rem] flex-1">
          <h2 className="text-base font-semibold text-slate-100">Experiments: prove which fix works</h2>
          <p className="mt-1 text-sm text-slate-400">
            Runs the same traffic and seed four times — <b>A</b> baseline, <b>B</b> bigger bottleneck, <b>C</b> queue policy RED and Priority — and compares measured results.
            The default is the 3-sender scenario: 6 + 5 + 4 = 15 Mbps offered into a 10 Mbps link.
          </p>
        </div>
        <label className="block">
          <span className="lbl">Scenario</span>
          <select className="input w-56" value={source} onChange={(e) => setSource(e.target.value)}>
            {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            <option value="current">Current simulator scenario</option>
          </select>
        </label>
        <button className="btn btn-primary" disabled={busy} onClick={run}>{busy ? 'Running 4 simulations…' : '▶ Run all (A, B, C)'}</button>
      </div>

      {error && <div className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</div>}
      {busy && <div className="card p-6 text-center text-slate-400">Simulating… this takes a few seconds.</div>}

      {res && !busy && (
        <>
          <div className="card border-ok/40 bg-ok/5 p-4 text-sm">
            <span className="mr-2 rounded bg-ok/20 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-ok">Verdict</span>
            {res.verdict}
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {res.experiments.map((e) => {
              const t = e.summary.totals
              return (
                <div key={e.id} className="card p-3.5" style={{ borderColor: e.id === res.best ? '#34d399' : undefined }}>
                  <div className="flex items-center justify-between">
                    <span className="font-semibold" style={{ color: EXP_COLORS[e.id] }}>Experiment {e.id}</span>
                    {e.id === res.best && <span className="chip border-ok/50 text-ok">best</span>}
                  </div>
                  <div className="text-sm font-medium text-slate-100">{e.name}</div>
                  <p className="mt-0.5 min-h-[2.5rem] text-[12px] text-slate-400">{e.description}</p>
                  <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[12px]">
                    <dt className="text-slate-500">Throughput</dt><dd className="text-right">{fmt(t.throughput_mbps)} Mbps</dd>
                    <dt className="text-slate-500">Loss</dt><dd className="text-right">{fmt(t.loss_pct, 1)} %</dd>
                    <dt className="text-slate-500">Avg delay</dt><dd className="text-right">{fmt(t.delay_avg_ms, 1)} ms</dd>
                    <dt className="text-slate-500">Fairness</dt><dd className="text-right">{fmt(t.jain, 3)}</dd>
                  </dl>
                </div>
              )
            })}
          </div>

          <div className="card overflow-x-auto">
            <div className="card-h"><span>Comparison table</span><span className="normal-case tracking-normal text-slate-500">Δ% vs baseline A · green = better, red = worse</span></div>
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-left text-[12px] text-slate-400">
                  <th className="px-3.5 py-1.5 font-medium">Metric</th>
                  {ids.map((id) => <th key={id} className="px-2 py-1.5 text-right font-medium" style={{ color: EXP_COLORS[id] }}>{id}</th>)}
                </tr>
              </thead>
              <tbody>
                {res.comparison.map((r) => (
                  <tr key={r.metric} className="border-t border-ink-600/60">
                    <td className="px-3.5 py-2">{r.label}{r.unit ? <span className="text-slate-500"> ({r.unit})</span> : null} <span className="text-[11px] text-slate-600">{dirHint(r.direction)}</span></td>
                    {ids.map((id, i) => {
                      const d = r.delta_pct[id]
                      const flag = r.flag[id]
                      return (
                        <td key={id} className="px-2 py-2 text-right font-mono">
                          {fmt(r.values[id], r.metric === 'jain' || r.metric.startsWith('bottleneck') ? 3 : 2)}
                          {i > 0 && (
                            <div className={`text-[11px] ${flag === 'better' ? 'text-ok' : flag === 'worse' ? 'text-bad' : 'text-slate-500'}`}>
                              {d === null || d === undefined ? 'n/a' : `${d > 0 ? '+' : ''}${d.toFixed(1)}%`}
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            {charts.map((c) => (
              <MetricChart key={c.title} title={c.title} unit={c.unit} data={c.rows} series={series} duration={duration} />
            ))}
          </div>

          <div className="card p-4 text-sm text-slate-300">
            <h3 className="mb-1 font-semibold text-slate-100">How to read this</h3>
            <ul className="list-disc space-y-1 pl-5 text-slate-400">
              <li><b className="text-slate-200">B</b> removes the cause: capacity now exceeds the 15 Mbps offered, so loss and queueing vanish.</li>
              <li><b className="text-slate-200">C-RED</b> keeps the queue shorter (lower delay) but cannot create capacity: loss stays about the same.</li>
              <li><b className="text-slate-200">C-PRIO</b> protects the high-priority sender, but the lowest class absorbs the loss and waits much longer (see p95 delay and fairness).</li>
            </ul>
          </div>
        </>
      )}
    </div>
  )
}
