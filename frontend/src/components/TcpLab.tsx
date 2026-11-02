import { useMemo, useState } from 'react'
import { post } from '../api'
import type { Policy, TcpLabResult } from '../types'
import { fmt } from '../lib'
import MetricChart from './MetricChart'
import type { Row, Series } from './MetricChart'
import { Num, Sel } from './fields'

const COL = { reno: '#f59e0b', cubic: '#7c9cff' }

export default function TcpLab() {
  const [bw, setBw] = useState(10)
  const [delay, setDelay] = useState(20)
  const [buf, setBuf] = useState(50)
  const [flows, setFlows] = useState(1)
  const [dur, setDur] = useState(30)
  const [seed, setSeed] = useState(1)
  const [policy, setPolicy] = useState<Policy>('droptail')
  const [res, setRes] = useState<TcpLabResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setBusy(true); setError(null)
    try {
      setRes(await post<TcpLabResult>('/api/tcp-lab', { bandwidth_mbps: bw, delay_ms: delay, buffer_pkts: buf, flows, duration_s: dur, seed, queue_policy: policy }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setRes(null)
    } finally {
      setBusy(false)
    }
  }

  const flowIds = res ? Object.keys(res.runs.reno.summary.flows) : []
  const charts = useMemo(() => {
    if (!res) return null
    const reno = res.runs.reno.samples
    const cubic = res.runs.cubic.samples
    const n = Math.min(reno.length, cubic.length)
    const cwnd: Row[] = []
    const queue: Row[] = []
    const tput: Row[] = []
    const cwSeries: Series[] = []
    for (const id of flowIds) {
      for (const v of ['reno', 'cubic'] as const) {
        cwSeries.push({ key: `${v}:${id}`, name: `${v === 'reno' ? 'Reno' : 'CUBIC'}${flowIds.length > 1 ? ` · ${id}` : ''}`, color: COL[v], dash: flowIds.indexOf(id) > 0 ? '4 3' : undefined })
      }
    }
    for (let i = 0; i < n; i++) {
      const t = reno[i].t
      const c: Row = { t }
      const q: Row = { t }
      const th: Row = { t }
      for (const v of ['reno', 'cubic'] as const) {
        const s = (v === 'reno' ? reno : cubic)[i]
        for (const id of flowIds) c[`${v}:${id}`] = s.flows[id]?.cwnd ?? null
        q[v] = s.links['R1>R2']?.qlen ?? null
        th[v] = s.global.goodput_mbps
      }
      cwnd.push(c); queue.push(q); tput.push(th)
    }
    return { cwnd, queue, tput, cwSeries }
  }, [res, flowIds.join(',')])

  const bdp = Math.round((bw * 1e6 * ((2 * (delay + 2 + 1)) / 1000)) / (1000 * 8))
  const two: Series[] = [{ key: 'reno', name: 'Reno', color: COL.reno }, { key: 'cubic', name: 'CUBIC', color: COL.cubic }]

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <h2 className="text-base font-semibold text-slate-100">TCP Lab: Reno vs CUBIC on the same bottleneck</h2>
        <p className="mt-1 text-sm text-slate-400">
          Identical network and seed, only the congestion-control algorithm changes. Watch the congestion window (cwnd): Reno climbs in straight lines, CUBIC follows a cubic curve that flattens near its last loss point.
          Both overshoot at start-up, then settle into a sawtooth that fills the buffer.
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <Num label="Bottleneck" unit="Mbps" value={bw} min={1} step={5} onChange={(v) => setBw(Math.max(1, v))} />
          <Num label="Link delay" unit="ms" value={delay} min={0} step={5} onChange={(v) => setDelay(Math.max(0, v))} />
          <Num label="Buffer" unit="pkts" value={buf} min={5} step={10} onChange={(v) => setBuf(Math.max(5, Math.round(v)))} />
          <Num label="TCP flows" value={flows} min={1} max={4} onChange={(v) => setFlows(Math.min(4, Math.max(1, Math.round(v))))} />
          <Num label="Duration" unit="s" value={dur} min={10} max={120} step={10} onChange={(v) => setDur(Math.min(120, Math.max(10, v)))} />
          <Num label="Seed" value={seed} onChange={(v) => setSeed(Math.round(v))} />
          <Sel label="Queue" value={policy} options={[{ value: 'droptail', label: 'DropTail' }, { value: 'red', label: 'RED' }]} onChange={setPolicy} />
          <div className="flex items-end"><button className="btn btn-primary w-full" disabled={busy} onClick={run}>{busy ? 'Running…' : '▶ Run Reno vs CUBIC'}</button></div>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">Bandwidth-delay product ≈ {bdp} packets (1000 B). Buffer + BDP ≈ {bdp + buf} packets is where cwnd peaks before a loss.</p>
      </div>

      {error && <div className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">{error}</div>}
      {busy && <div className="card p-6 text-center text-slate-400">Simulating both variants…</div>}

      {res && charts && !busy && (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            {(['reno', 'cubic'] as const).map((v) => {
              const t = res.runs[v].summary.totals
              const fs = Object.values(res.runs[v].summary.flows)
              const sum = (k: 'retransmits' | 'timeouts' | 'fast_retransmits') => fs.reduce((a, f) => a + (f[k] ?? 0), 0)
              return (
                <div key={v} className="card p-3.5" style={{ borderColor: COL[v] }}>
                  <div className="font-semibold" style={{ color: COL[v] }}>{v === 'reno' ? 'TCP Reno' : 'TCP CUBIC'}</div>
                  <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[12px] sm:grid-cols-3">
                    <dt className="text-slate-500">Goodput</dt><dd className="text-right">{fmt(t.goodput_mbps)} Mbps</dd>
                    <dt className="text-slate-500 sm:hidden">Avg delay</dt><dd className="text-right sm:hidden">{fmt(t.delay_avg_ms, 1)} ms</dd>
                    <dt className="hidden text-slate-500 sm:block">Avg delay</dt><dd className="hidden text-right sm:block">{fmt(t.delay_avg_ms, 1)} ms</dd>
                    <dt className="text-slate-500">Loss</dt><dd className="text-right">{fmt(t.loss_pct, 2)} %</dd>
                    <dt className="text-slate-500">Fast retransmits</dt><dd className="text-right">{sum('fast_retransmits')}</dd>
                    <dt className="text-slate-500">Timeouts</dt><dd className="text-right">{sum('timeouts')}</dd>
                    <dt className="text-slate-500">Fairness (Jain)</dt><dd className="text-right">{fmt(t.jain, 3)}</dd>
                  </dl>
                </div>
              )
            })}
          </div>
          <MetricChart title="Congestion window (cwnd)" unit="segments" data={charts.cwnd} series={charts.cwSeries} duration={dur} height={260}
            note="Each drop in cwnd is a loss event. Reno halves its window; CUBIC cuts it to 70% and then regrows along a cubic curve." />
          <div className="grid gap-3 lg:grid-cols-2">
            <MetricChart title="Bottleneck queue length" unit="packets" data={charts.queue} series={two} duration={dur} />
            <MetricChart title="Goodput" unit="Mbps" data={charts.tput} series={two} duration={dur} />
          </div>
        </>
      )}
    </div>
  )
}
