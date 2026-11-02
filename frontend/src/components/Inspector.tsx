import { useState } from 'react'
import type { FlowCfg, LinkCfg, SimConfig } from '../types'
import { clone, uid } from '../lib'
import type { Selection } from './TopologyCanvas'
import { Num, Sel, Section, Txt } from './fields'

interface Props {
  config: SimConfig
  selected: Selection | null
  onChange: (c: SimConfig) => void
  onSelect: (s: Selection | null) => void
}

export default function Inspector({ config, selected, onChange, onSelect }: Props) {
  const [target, setTarget] = useState('')
  const edit = (fn: (c: SimConfig) => void) => { const c = clone(config); fn(c); onChange(c) }
  const label = (id: string) => config.nodes.find((n) => n.id === id)?.label ?? id

  const builder = (
    <div className="mt-3 flex flex-wrap gap-2 border-t border-ink-600/60 pt-3">
      <button className="btn btn-sm" onClick={() => edit((c) => {
        const id = uid('H', c.nodes.map((n) => n.id)); c.nodes.push({ id, type: 'host', label: `Host ${id.slice(1)}`, x: 120, y: 60 })
        onSelect({ kind: 'node', id })
      })}>+ Host</button>
      <button className="btn btn-sm" onClick={() => edit((c) => {
        const id = uid('R', c.nodes.map((n) => n.id)); c.nodes.push({ id, type: 'router', label: `Router ${id.slice(1)}`, x: 500, y: 60 })
        onSelect({ kind: 'node', id })
      })}>+ Router</button>
      <button className="btn btn-sm" disabled={c2hosts(config) < 2} onClick={() => edit((c) => {
        const hosts = c.nodes.filter((n) => n.type === 'host')
        const id = uid('flow', c.flows.map((f) => f.id))
        c.flows.push({ id, src: hosts[0].id, dst: hosts[hosts.length - 1].id, kind: 'cbr', rate_mbps: 2, packet_size: 1000, priority: 1,
          burstiness: 4, burst_on_ms: 100, tcp_variant: 'reno', label: `Flow ${id.slice(4)}` })
        onSelect({ kind: 'flow', id })
      })}>+ Flow</button>
    </div>
  )

  if (!selected) {
    return (
      <Section title="Inspector">
        <p className="text-sm text-slate-400">Click a node, link or flow to edit it. Drag nodes on the canvas to rearrange them.</p>
        {builder}
      </Section>
    )
  }

  if (selected.kind === 'node') {
    const n = config.nodes.find((x) => x.id === selected.id)
    if (!n) return null
    const others = config.nodes.filter((x) => x.id !== n.id)
    return (
      <Section title={`Node · ${n.id}`}>
        <div className="grid grid-cols-2 gap-2">
          <Txt label="Label" value={n.label} onChange={(v) => edit((c) => { c.nodes.find((x) => x.id === n.id)!.label = v })} />
          <Sel label="Type" value={n.type} options={[{ value: 'host', label: 'Host' }, { value: 'router', label: 'Router' }]}
            onChange={(v) => edit((c) => { c.nodes.find((x) => x.id === n.id)!.type = v })} />
        </div>
        <div className="mt-3 flex gap-2">
          <select className="input" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Connect to…</option>
            {others.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
          <button className="btn btn-sm" disabled={!target} onClick={() => edit((c) => {
            const id = uid('L', c.links.map((l) => l.id))
            c.links.push({ id, a: n.id, b: target, bandwidth_mbps: 10, delay_ms: 5, buffer_pkts: 50, loss_prob: 0, queue_policy: 'droptail' })
            onSelect({ kind: 'link', id }); setTarget('')
          })}>Link</button>
        </div>
        <button className="btn btn-sm mt-3 text-bad" onClick={() => edit((c) => {
          c.nodes = c.nodes.filter((x) => x.id !== n.id)
          c.links = c.links.filter((l) => l.a !== n.id && l.b !== n.id)
          c.flows = c.flows.filter((f) => f.src !== n.id && f.dst !== n.id)
          onSelect(null)
        })}>Delete node (and its links/flows)</button>
        {builder}
      </Section>
    )
  }

  if (selected.kind === 'link') {
    const l = config.links.find((x) => x.id === selected.id)
    if (!l) return null
    const set = <K extends keyof LinkCfg>(k: K, v: LinkCfg[K]) => edit((c) => { const t = c.links.find((x) => x.id === l.id)!; t[k] = v })
    return (
      <Section title={`Link · ${label(l.a)} ↔ ${label(l.b)}`}>
        <div className="grid grid-cols-2 gap-2">
          <Num label="Bandwidth" unit="Mbps" value={l.bandwidth_mbps} min={0.1} step={1} onChange={(v) => set('bandwidth_mbps', Math.max(0.1, v))} />
          <Num label="Propagation delay" unit="ms" value={l.delay_ms} min={0} step={1} onChange={(v) => set('delay_ms', Math.max(0, v))} />
          <Num label="Buffer" unit="packets" value={l.buffer_pkts} min={1} step={10} onChange={(v) => set('buffer_pkts', Math.max(1, Math.round(v)))} />
          <Num label="Random loss" unit="%" value={+(l.loss_prob * 100).toFixed(3)} min={0} max={100} step={0.1}
            onChange={(v) => set('loss_prob', Math.min(1, Math.max(0, v / 100)))} />
        </div>
        <div className="mt-2">
          <Sel label="Queue policy (both directions)" value={l.queue_policy}
            options={[{ value: 'droptail', label: 'DropTail (FIFO)' }, { value: 'red', label: 'RED (early drop)' }, { value: 'priority', label: 'Priority (3 classes)' }]}
            onChange={(v) => set('queue_policy', v)} />
        </div>
        {l.queue_policy === 'red' && (
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Num label="min_th" unit="pkts" value={l.red_min_th ?? Math.max(1, Math.round(0.2 * l.buffer_pkts))} onChange={(v) => set('red_min_th', v)} />
            <Num label="max_th" unit="pkts" value={l.red_max_th ?? Math.round(0.6 * l.buffer_pkts)} onChange={(v) => set('red_max_th', v)} />
            <Num label="max_p" value={l.red_max_p ?? 0.1} step={0.01} min={0.001} max={1} onChange={(v) => set('red_max_p', v)} />
            <Num label="EWMA weight" value={l.red_wq ?? 0.02} step={0.005} min={0.0001} max={1} onChange={(v) => set('red_wq', v)} />
          </div>
        )}
        <button className="btn btn-sm mt-3 text-bad" onClick={() => edit((c) => { c.links = c.links.filter((x) => x.id !== l.id); onSelect(null) })}>Delete link</button>
        {builder}
      </Section>
    )
  }

  const f = config.flows.find((x) => x.id === selected.id)
  if (!f) return null
  const set = <K extends keyof FlowCfg>(k: K, v: FlowCfg[K]) => edit((c) => { const t = c.flows.find((x) => x.id === f.id)!; t[k] = v })
  const hosts = config.nodes.filter((n) => n.type === 'host').map((n) => ({ value: n.id, label: n.label }))
  return (
    <Section title={`Flow · ${f.label ?? f.id}`}>
      <div className="grid grid-cols-2 gap-2">
        <Sel label="From" value={f.src} options={hosts} onChange={(v) => set('src', v)} />
        <Sel label="To" value={f.dst} options={hosts} onChange={(v) => set('dst', v)} />
        <Sel label="Traffic type" value={f.kind}
          options={[{ value: 'cbr', label: 'CBR (constant)' }, { value: 'poisson', label: 'Poisson' }, { value: 'bursty', label: 'Bursty on/off' }, { value: 'tcp', label: 'TCP (greedy)' }]}
          onChange={(v) => set('kind', v)} />
        {f.kind === 'tcp'
          ? <Sel label="TCP variant" value={f.tcp_variant} options={[{ value: 'reno', label: 'Reno' }, { value: 'cubic', label: 'CUBIC' }]} onChange={(v) => set('tcp_variant', v)} />
          : <Num label="Rate" unit="Mbps" value={f.rate_mbps} min={0.1} step={0.5} onChange={(v) => set('rate_mbps', Math.max(0.1, v))} />}
        <Num label="Packet size" unit="bytes" value={f.packet_size} min={64} max={9000} step={100} onChange={(v) => set('packet_size', Math.round(v))} />
        <Sel label="Priority class" value={String(f.priority)} options={[{ value: '0', label: '0 (highest)' }, { value: '1', label: '1' }, { value: '2', label: '2 (lowest)' }]}
          onChange={(v) => set('priority', Number(v))} />
        {f.kind === 'bursty' && <Num label="Burstiness (peak/avg)" value={f.burstiness} min={1} step={0.5} onChange={(v) => set('burstiness', v)} />}
        <Num label="Start" unit="s" value={f.start_s ?? 0} min={0} step={0.5} onChange={(v) => set('start_s', Math.max(0, v))} />
      </div>
      <button className="btn btn-sm mt-3 text-bad" onClick={() => edit((c) => { c.flows = c.flows.filter((x) => x.id !== f.id); onSelect(null) })}>Delete flow</button>
      {builder}
    </Section>
  )
}

function c2hosts(c: SimConfig): number {
  return c.nodes.filter((n) => n.type === 'host').length
}
