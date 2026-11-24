import { useState } from 'react'
import type { EventCfg, FlowCfg, LinkCfg, SimConfig } from '../types'
import { bottleneckLinkId, clone, uid } from '../lib'
import type { Selection } from './TopologyCanvas'
import { Num, Sel, Section } from './fields'

interface Props {
  config: SimConfig
  onChange: (c: SimConfig) => void
  speed: number
  onSpeed: (v: number) => void
  selected: Selection | null
  onSelect: (s: Selection | null) => void
}

export default function Controls({ config, onChange, speed, onSpeed, selected, onSelect }: Props) {
  const edit = (fn: (c: SimConfig) => void) => { const c = clone(config); fn(c); onChange(c) }
  const setAll = <K extends keyof FlowCfg>(k: K, v: FlowCfg[K]) => edit((c) => { c.flows.forEach((f) => { f[k] = v }) })
  const bnId = bottleneckLinkId(config)
  const bn = config.links.find((l) => l.id === bnId)
  const setBn = <K extends keyof LinkCfg>(k: K, v: LinkCfg[K]) => edit((c) => {
    const l = c.links.find((x) => x.id === bnId)
    if (l) { l[k] = v; if (k === 'buffer_pkts') { l.red_min_th = null; l.red_max_th = null } }
  })
  const rateFlows = config.flows.filter((f) => f.kind !== 'tcp')
  const avgRate = rateFlows.length ? rateFlows.reduce((s, f) => s + f.rate_mbps, 0) / rateFlows.length : 0
  const first = config.flows[0]
  const senderCount = new Set(config.flows.map((f) => f.src)).size

  // The sender count controls visible host nodes as well as traffic flows.
  // Previously it only cloned flows, so the UI could show 7 flows but still
  // display only the original 3 sender hosts.
  const setCount = (n: number) => edit((c) => {
    const sources = [...new Set(c.flows.map((f) => f.src))]
    const sourceNodes = sources
      .map((id) => c.nodes.find((node) => node.id === id))
      .filter((node): node is NonNullable<typeof node> => Boolean(node && node.type === 'host'))

    if (n < sources.length) {
      const removed = new Set(sources.slice(n))
      c.flows = c.flows.filter((flow) => !removed.has(flow.src))
      const stillReferenced = new Set(c.flows.flatMap((flow) => [flow.src, flow.dst]))
      for (const id of removed) {
        if (!stillReferenced.has(id)) {
          c.nodes = c.nodes.filter((node) => node.id !== id)
          c.links = c.links.filter((link) => link.a !== id && link.b !== id)
        }
      }
      return
    }

    if (n <= sources.length) return

    const template = c.flows[c.flows.length - 1] ?? c.flows[0]
    const destination = template?.dst ?? c.nodes.find((node) => node.type === 'host' && !sources.includes(node.id))?.id
    const primarySource = sources[0]
    const primaryLink = c.links.find((link) =>
      (link.a === primarySource && c.nodes.find((node) => node.id === link.b)?.type === 'router') ||
      (link.b === primarySource && c.nodes.find((node) => node.id === link.a)?.type === 'router'),
    )
    const routerId = primaryLink
      ? (primaryLink.a === primarySource ? primaryLink.b : primaryLink.a)
      : c.nodes.find((node) => node.type === 'router')?.id
    const router = c.nodes.find((node) => node.id === routerId)

    // A sender needs a reachable destination and a router/access node.
    if (!destination || !router) return

    const baseX = sourceNodes.length ? Math.min(...sourceNodes.map((node) => node.x)) : 90
    const rows = [50, 115, 180, 245, 310, 375, 440, 505]
    const columns = [baseX + 80, baseX + 160, baseX + 240, baseX, Math.max(45, baseX - 80)]
    const pickPosition = () => {
      let best: { x: number; y: number; score: number } | null = null
      for (const x of columns) {
        if (x < 35 || x > 820) continue
        for (const y of rows) {
          const nearest = Math.min(...c.nodes.map((node) => Math.hypot(node.x - x, node.y - y)))
          if (nearest < 66) continue
          const score = Math.abs(x - (baseX + 80)) + Math.abs(y - router.y) * 0.12
          if (!best || score < best.score) best = { x, y, score }
        }
      }
      if (best) return { x: best.x, y: best.y }
      const index = c.nodes.filter((node) => node.type === 'host').length
      return { x: Math.min(760, baseX + 160), y: 45 + (index % 7) * 75 }
    }

    for (let index = sources.length; index < n; index++) {
      const number = index + 1
      const nodeId = uid('NP_SENDER_', c.nodes.map((node) => node.id))
      const position = pickPosition()
      c.nodes.push({ id: nodeId, type: 'host', label: `Sender ${number}`, ...position })

      const linkId = uid('NP_L', c.links.map((link) => link.id))
      const link = primaryLink
        ? { ...primaryLink, id: linkId, a: nodeId, b: router.id }
        : { id: linkId, a: nodeId, b: router.id, bandwidth_mbps: 100, delay_ms: 2, buffer_pkts: 100,
            loss_prob: 0, queue_policy: 'droptail' as const }
      c.links.push(link)

      const flowId = uid('f', c.flows.map((flow) => flow.id))
      const flow: FlowCfg = template
        ? { ...template, id: flowId, src: nodeId, dst: destination, label: `Sender ${number} (${template.rate_mbps} Mbps)` }
        : { id: flowId, src: nodeId, dst: destination, kind: 'cbr', rate_mbps: 4, packet_size: 1000, priority: 1,
            burstiness: 4, burst_on_ms: 100, tcp_variant: 'reno', label: `Sender ${number}` }
      c.flows.push(flow)
    }
  })

  return (
    <div className="space-y-3">
      <Section title="Traffic">
        <div className="grid grid-cols-2 gap-2">
          <Num label="Number of senders" value={senderCount} min={0} max={12} onChange={(v) => setCount(Math.max(0, Math.min(12, Math.round(v))))} />
          <Num label="Rate per flow" unit="Mbps" value={+avgRate.toFixed(2)} min={0.1} step={0.5}
            onChange={(v) => edit((c) => { c.flows.forEach((f) => { if (f.kind !== 'tcp') f.rate_mbps = Math.max(0.1, v) }) })} />
          <Num label="Packet size" unit="bytes" value={first?.packet_size ?? 1000} min={64} max={9000} step={100} onChange={(v) => setAll('packet_size', Math.round(v))} />
          <Num label="Burstiness" value={first?.burstiness ?? 4} min={1} step={0.5} onChange={(v) => setAll('burstiness', Math.max(1, v))} />
          <Sel label="Traffic type (all)" value={first?.kind ?? 'cbr'}
            options={[{ value: 'cbr', label: 'CBR' }, { value: 'poisson', label: 'Poisson' }, { value: 'bursty', label: 'Bursty' }, { value: 'tcp', label: 'TCP' }]}
            onChange={(v) => setAll('kind', v)} />
          <Sel label="TCP variant" value={config.flows.find((f) => f.kind === 'tcp')?.tcp_variant ?? 'reno'}
            options={[{ value: 'reno', label: 'Reno' }, { value: 'cubic', label: 'CUBIC' }]}
            onChange={(v) => edit((c) => { c.flows.forEach((f) => { f.tcp_variant = v }) })} />
        </div>
        <p className="mt-2 text-[11px] text-slate-500">Each sender is shown as a separate host connected to the router.</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {config.flows.map((f) => (
            <button key={f.id} className={`chip hover:border-pulse ${selected?.kind === 'flow' && selected.id === f.id ? 'border-pulse text-pulse-soft' : ''}`}
              onClick={() => onSelect({ kind: 'flow', id: f.id })}>{f.label ?? f.id}</button>
          ))}
        </div>
      </Section>

      <Section title={`Bottleneck link${bn ? ` · ${bn.id}` : ''}`}>
        {bn ? (
          <div className="grid grid-cols-2 gap-2">
            <Num label="Bandwidth" unit="Mbps" value={bn.bandwidth_mbps} min={0.5} step={1} onChange={(v) => setBn('bandwidth_mbps', Math.max(0.1, v))} />
            <Num label="Buffer" unit="packets" value={bn.buffer_pkts} min={1} step={10} onChange={(v) => setBn('buffer_pkts', Math.max(1, Math.round(v)))} />
            <div className="col-span-2">
              <Sel label="Queue policy" value={bn.queue_policy}
                options={[{ value: 'droptail', label: 'DropTail (FIFO)' }, { value: 'red', label: 'RED' }, { value: 'priority', label: 'Priority queue' }]}
                onChange={(v) => setBn('queue_policy', v)} />
            </div>
          </div>
        ) : <p className="text-sm text-slate-500">This topology has no links yet.</p>}
      </Section>

      <Section title="Run settings">
        <div className="grid grid-cols-2 gap-2">
          <Num label="Seed" value={config.seed} step={1} onChange={(v) => edit((c) => { c.seed = Math.round(v) })} />
          <Num label="Duration" unit="s" value={config.duration_s} min={1} max={120} step={5} onChange={(v) => edit((c) => { c.duration_s = Math.min(120, Math.max(1, v)) })} />
          <div className="col-span-2">
            <Sel label="Simulation speed" value={String(speed)}
              options={['0.25', '0.5', '1', '2', '5', '10'].map((s) => ({ value: s, label: `${s}× real time` }))}
              onChange={(v) => onSpeed(Number(v))} />
          </div>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">Same config + same seed ⇒ identical results.</p>
      </Section>

      <EventsEditor config={config} onChange={onChange} />
    </div>
  )
}

function EventsEditor({ config, onChange }: { config: SimConfig; onChange: (c: SimConfig) => void }) {
  const hosts = config.nodes.filter((n) => n.type === 'host')
  const [kind, setKind] = useState<'link_failure' | 'burst'>('burst')
  const [time, setTime] = useState(6)
  const [dur, setDur] = useState(4)
  const [link, setLink] = useState(config.links[0]?.id ?? '')
  const [rate, setRate] = useState(20)
  const first = config.flows[0]

  const add = () => {
    const c = clone(config)
    const ev: EventCfg = kind === 'link_failure'
      ? { type: 'link_failure', time, duration: dur, link: link || c.links[0]?.id }
      : { type: 'burst', time, duration: dur, rate_mbps: rate, src: first?.src ?? hosts[0]?.id, dst: first?.dst ?? hosts[hosts.length - 1]?.id, priority: 1,
          label: 'Flash crowd / DDoS' }
    if (ev.type === 'link_failure' && !ev.link) return
    c.events.push(ev)
    onChange(c)
  }
  return (
    <Section title="What-if events">
      <div className="grid grid-cols-2 gap-2">
        <div className="col-span-2">
          <Sel label="Event" value={kind} options={[{ value: 'burst', label: 'Flash crowd / DDoS burst' }, { value: 'link_failure', label: 'Link failure' }]} onChange={setKind} />
        </div>
        {kind === 'link_failure' && (
          <div className="col-span-2">
            <Sel label="Link" value={link || (config.links[0]?.id ?? '')}
              options={config.links.map((l) => ({ value: l.id, label: `${l.id} (${l.a}↔${l.b})` }))} onChange={setLink} />
          </div>
        )}
        <Num label="At time" unit="s" value={time} min={0} step={1} onChange={setTime} />
        <Num label="Lasts" unit="s" value={dur} min={0.5} step={1} onChange={setDur} />
        {kind === 'burst' && <Num label="Extra rate" unit="Mbps" value={rate} min={1} step={5} onChange={setRate} />}
      </div>
      <button className="btn btn-sm mt-2" onClick={add}>+ Add event</button>
      <ul className="mt-2 space-y-1">
        {config.events.map((e, i) => (
          <li key={i} className="flex items-center justify-between rounded-md bg-ink-900/70 px-2 py-1 text-xs">
            <span>{e.type === 'burst' ? '⚡' : '✕'} {e.type === 'burst' ? `+${e.rate_mbps} Mbps` : `link ${e.link}`} @ {e.time}s for {e.duration ?? '∞'}s</span>
            <button className="text-slate-500 hover:text-bad" aria-label="Remove event"
              onClick={() => { const c = clone(config); c.events.splice(i, 1); onChange(c) }}>✕</button>
          </li>
        ))}
        {config.events.length === 0 && <li className="text-xs text-slate-500">No events. Add one to see how the network reacts.</li>}
      </ul>
    </Section>
  )
}
