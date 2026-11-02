import { useMemo } from 'react'
import type { Marker, Sample, SimConfig, Summary } from '../types'
import { fmt, flowColor } from '../lib'
import MetricChart from './MetricChart'
import type { Row, Series } from './MetricChart'

interface Props {
  config: SimConfig
  samples: Sample[]
  markers: Marker[]
  duration: number
  summary: Summary | null
}

const PORT_COLORS = ['#7c9cff', '#f59e0b', '#34d399', '#f472b6', '#22d3ee', '#a78bfa']

export default function Dashboard({ config, samples, markers, duration, summary }: Props) {
  const label = (id: string) => config.nodes.find((n) => n.id === id)?.label ?? id
  const flowName = (id: string) => config.flows.find((f) => f.id === id)?.label ?? summary?.flows[id]?.label ?? id

  const { flowIds, ports } = useMemo(() => {
    const fset: string[] = []
    const pmax: Record<string, number> = {}
    for (const s of samples) {
      for (const id of Object.keys(s.flows)) if (!fset.includes(id)) fset.push(id)
      for (const [pid, l] of Object.entries(s.links)) pmax[pid] = Math.max(pmax[pid] ?? 0, l.util * 10 + l.qmax)
    }
    const top = Object.entries(pmax).filter(([, v]) => v > 0.6).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([pid]) => pid)
    return { flowIds: fset, ports: top }
  }, [samples])

  const flowSeries = (): Series[] => flowIds.map((id) => ({ key: id, name: flowName(id), color: flowColor(config, id) }))
  const portName = (pid: string) => { const [a, b] = pid.split('>'); return `${label(a)}→${label(b)}` }
  const portSeries: Series[] = ports.map((pid, i) => ({ key: pid, name: portName(pid), color: PORT_COLORS[i % PORT_COLORS.length] }))

  const rows = useMemo(() => ({
    tput: samples.map((s): Row => ({ t: s.t, Total: s.global.throughput_mbps, ...Object.fromEntries(Object.entries(s.flows).map(([k, v]) => [k, v.throughput_mbps])) })),
    delay: samples.map((s): Row => ({ t: s.t, ...Object.fromEntries(Object.entries(s.flows).map(([k, v]) => [k, v.delay_avg_ms])) })),
    loss: samples.map((s): Row => ({ t: s.t, ...Object.fromEntries(Object.entries(s.flows).map(([k, v]) => [k, v.loss_pct])) })),
    queue: samples.map((s): Row => ({ t: s.t, ...Object.fromEntries(ports.map((p) => [p, s.links[p]?.qlen ?? null])) })),
    util: samples.map((s): Row => ({ t: s.t, ...Object.fromEntries(ports.map((p) => [p, s.links[p] ? +(s.links[p].util * 100).toFixed(1) : null])) })),
    jain: samples.map((s): Row => ({ t: s.t, Jain: s.global.jain })),
  }), [samples, ports])

  const last = samples[samples.length - 1]
  const kpi = summary
    ? [['Throughput', fmt(summary.totals.throughput_mbps), 'Mbps'], ['Goodput', fmt(summary.totals.goodput_mbps), 'Mbps'],
       ['Loss', fmt(summary.totals.loss_pct, 1), '%'], ['Avg delay', fmt(summary.totals.delay_avg_ms, 1), 'ms'],
       ['p95 delay', fmt(summary.totals.delay_p95_ms, 1), 'ms'], ['Fairness', fmt(summary.totals.jain, 3), 'Jain']]
    : last
      ? [['Throughput', fmt(last.global.throughput_mbps), 'Mbps'], ['Goodput', fmt(last.global.goodput_mbps), 'Mbps'],
         ['Loss', fmt(last.global.loss_pct, 1), '%'], ['Avg delay', fmt(last.global.delay_avg_ms, 1), 'ms'],
         ['Max util', fmt(last.global.max_util * 100, 0), '%'], ['Fairness', fmt(last.global.jain, 3), 'Jain']]
      : []

  const totalSeries: Series = { key: 'Total', name: 'Total', color: '#e2e8f0', dash: '5 3', width: 2.4 }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
        {(kpi.length ? kpi : [['Throughput', '–', 'Mbps'], ['Goodput', '–', 'Mbps'], ['Loss', '–', '%'], ['Avg delay', '–', 'ms'], ['Max util', '–', '%'], ['Fairness', '–', 'Jain']]).map(([k, v, u]) => (
          <div key={k} className="card px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">{k}{summary ? ' · run' : ' · live'}</div>
            <div className="font-mono text-lg font-medium text-slate-100">{v}<span className="ml-1 text-[11px] text-slate-500">{u}</span></div>
          </div>
        ))}
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <MetricChart title="Throughput" unit="Mbps" data={rows.tput} series={[totalSeries, ...flowSeries()]} markers={markers} duration={duration} />
        <MetricChart title="Delay (average per flow)" unit="ms" data={rows.delay} series={flowSeries()} markers={markers} duration={duration} />
        <MetricChart title="Packet loss" unit="% of packets sent" data={rows.loss} series={flowSeries()} markers={markers} duration={duration} yDomain={[0, 'auto']} />
        <MetricChart title="Queue length" unit="packets" data={rows.queue} series={portSeries} markers={markers} duration={duration} />
        <MetricChart title="Link utilization" unit="%" data={rows.util} series={portSeries} markers={markers} duration={duration} yDomain={[0, 100]} />
        <MetricChart title="Fairness (Jain's index)" unit="1 = perfectly fair" data={rows.jain}
          series={[{ key: 'Jain', name: 'Jain index', color: '#a78bfa' }]} markers={markers} duration={duration} yDomain={[0, 1]} />
      </div>
    </div>
  )
}
