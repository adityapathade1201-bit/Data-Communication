import { useEffect, useRef } from 'react'
import type { MutableRefObject, PointerEvent as ReactPointerEvent } from 'react'
import type { Frame, NodeCfg, SimConfig } from '../types'
import { flowColor, portIds, utilColor } from '../lib'

export interface Selection { kind: 'node' | 'link' | 'flow'; id: string }

interface Props {
  config: SimConfig
  frameRef: MutableRefObject<Frame | null>
  selected: Selection | null
  onSelect: (s: Selection | null) => void
  onMoveNode: (id: string, x: number, y: number) => void
}

const W = 1000
const H = 560

interface Flash { x: number; y: number; t0: number }

function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy || 1
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

export default function TopologyCanvas({ config, frameRef, selected, onSelect, onMoveNode }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const cfgRef = useRef(config)
  const selRef = useRef(selected)
  const scaleRef = useRef(1)
  const dprRef = useRef(1)
  const dragRef = useRef<string | null>(null)
  const flashes = useRef<Flash[]>([])
  const lastFrame = useRef<Frame | null>(null)
  cfgRef.current = config
  selRef.current = selected

  // keep the canvas sharp and sized to its container
  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return
    const resize = () => {
      const cssW = Math.max(320, wrap.clientWidth)
      const cssH = cssW * (H / W)
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(cssW * dpr)
      canvas.height = Math.round(cssH * dpr)
      canvas.style.width = `${cssW}px`
      canvas.style.height = `${cssH}px`
      scaleRef.current = cssW / W
      dprRef.current = dpr
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [])

  // animation loop (reads everything from refs so React re-renders stay cheap)
  useEffect(() => {
    let raf = 0
    const draw = () => {
      raf = requestAnimationFrame(draw)
      const canvas = canvasRef.current
      const ctx = canvas?.getContext('2d')
      if (!canvas || !ctx) return
      const cfg = cfgRef.current
      const frame = frameRef.current
      const sel = selRef.current
      const now = performance.now()
      const k = scaleRef.current * dprRef.current
      ctx.setTransform(k, 0, 0, k, 0, 0)
      ctx.clearRect(0, 0, W, H)

      // faint dot grid
      ctx.fillStyle = 'rgba(124,156,255,0.07)'
      for (let gx = 20; gx < W; gx += 40) for (let gy = 20; gy < H; gy += 40) ctx.fillRect(gx, gy, 1.6, 1.6)

      const nodes: Record<string, NodeCfg> = {}
      cfg.nodes.forEach((n) => { nodes[n.id] = n })

      // which link is the live bottleneck?
      let hot: string | null = null
      let hotScore = 0
      for (const l of cfg.links) {
        const [pf, pr] = portIds(l)
        const u = Math.max(frame?.util[pf] ?? 0, frame?.util[pr] ?? 0)
        const q = Math.max((frame?.queues[pf] ?? 0) / l.buffer_pkts, (frame?.queues[pr] ?? 0) / l.buffer_pkts)
        const score = u + q
        if ((u >= 0.9 || q >= 0.4) && score > hotScore) { hot = l.id; hotScore = score }
      }

      // links
      for (const l of cfg.links) {
        const A = nodes[l.a]
        const B = nodes[l.b]
        if (!A || !B) continue
        const [pf, pr] = portIds(l)
        const u = Math.max(frame?.util[pf] ?? 0, frame?.util[pr] ?? 0)
        const down = frame?.up?.[pf] === false
        const isSel = sel?.kind === 'link' && sel.id === l.id
        if (hot === l.id && !down) {
          ctx.save()
          ctx.strokeStyle = 'rgba(248,113,113,0.28)'
          ctx.lineWidth = 15 + 3 * Math.sin(now / 220)
          ctx.lineCap = 'round'
          ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke()
          ctx.restore()
        }
        if (isSel) {
          ctx.strokeStyle = 'rgba(124,156,255,0.45)'
          ctx.lineWidth = 11
          ctx.lineCap = 'round'
          ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke()
        }
        ctx.lineCap = 'round'
        ctx.lineWidth = 2.5 + Math.min(4, Math.log10(Math.max(1, l.bandwidth_mbps)) * 1.3)
        ctx.strokeStyle = down ? '#475569' : frame ? utilColor(u) : '#3b4d6e'
        ctx.setLineDash(down ? [8, 8] : [])
        ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke()
        ctx.setLineDash([])

        const mx = (A.x + B.x) / 2
        const my = (A.y + B.y) / 2
        const label = down ? 'LINK DOWN' : `${l.bandwidth_mbps >= 1 ? +l.bandwidth_mbps.toFixed(1) : l.bandwidth_mbps} Mbps · ${l.delay_ms} ms`
        ctx.font = '500 11px "IBM Plex Mono", monospace'
        const tw = ctx.measureText(label).width
        ctx.fillStyle = 'rgba(8,13,24,0.88)'
        roundRect(ctx, mx - tw / 2 - 5, my - 20, tw + 10, 16, 5); ctx.fill()
        ctx.fillStyle = down ? '#f87171' : '#9fb3d1'
        ctx.textAlign = 'center'
        ctx.fillText(label, mx, my - 8)
        if (hot === l.id && !down) {
          ctx.fillStyle = '#f87171'
          ctx.font = '700 10px "IBM Plex Sans", sans-serif'
          ctx.fillText('BOTTLENECK', mx, my + 14)
        }
        if (down) {
          ctx.strokeStyle = '#f87171'; ctx.lineWidth = 3
          ctx.beginPath(); ctx.moveTo(mx - 7, my - 7); ctx.lineTo(mx + 7, my + 7)
          ctx.moveTo(mx + 7, my - 7); ctx.lineTo(mx - 7, my + 7); ctx.stroke()
        }

        // queue-fill bars next to each output port
        for (const [pid, from, to] of [[pf, A, B], [pr, B, A]] as [string, NodeCfg, NodeCfg][]) {
          const q = frame?.queues[pid] ?? 0
          const forward = pid === pf
          if (!forward && q === 0) continue
          const dx = to.x - from.x
          const dy = to.y - from.y
          const len = Math.hypot(dx, dy) || 1
          const t = 0.3
          const bx = from.x + dx * t + (-dy / len) * 15
          const by = from.y + dy * t + (dx / len) * 15
          const fill = Math.min(1, q / l.buffer_pkts)
          ctx.fillStyle = 'rgba(8,13,24,0.9)'
          roundRect(ctx, bx - 4, by - 14, 8, 28, 3); ctx.fill()
          ctx.strokeStyle = '#2e4268'; ctx.lineWidth = 1
          roundRect(ctx, bx - 4, by - 14, 8, 28, 3); ctx.stroke()
          if (fill > 0) {
            ctx.fillStyle = utilColor(0.4 + fill * 0.55)
            ctx.fillRect(bx - 3, by + 13 - 26 * fill, 6, 26 * fill)
          }
        }
      }

      // drop flashes (new drops reported by this frame)
      if (frame && frame !== lastFrame.current) {
        lastFrame.current = frame
        for (const pid of Object.keys(frame.drops)) {
          const [s, d] = pid.split('>')
          const S = nodes[s]
          const D = nodes[d]
          if (S && D) flashes.current.push({ x: S.x + (D.x - S.x) * 0.3, y: S.y + (D.y - S.y) * 0.3, t0: now })
        }
        if (flashes.current.length > 80) flashes.current.splice(0, flashes.current.length - 80)
      }
      flashes.current = flashes.current.filter((f) => now - f.t0 < 450)
      for (const f of flashes.current) {
        const a = (now - f.t0) / 450
        ctx.strokeStyle = `rgba(248,113,113,${1 - a})`
        ctx.fillStyle = `rgba(239,68,68,${0.8 * (1 - a)})`
        ctx.lineWidth = 2.5
        ctx.beginPath(); ctx.arc(f.x, f.y, 5 + a * 20, 0, Math.PI * 2); ctx.stroke()
        ctx.beginPath(); ctx.arc(f.x, f.y, 4, 0, Math.PI * 2); ctx.fill()
      }

      // packets
      if (frame) {
        for (const [pid, p, kind, flow] of frame.packets) {
          const [s, d] = pid.split('>')
          const S = nodes[s]
          const D = nodes[d]
          if (!S || !D) continue
          const dx = D.x - S.x
          const dy = D.y - S.y
          const len = Math.hypot(dx, dy) || 1
          const x = S.x + dx * p + (-dy / len) * 5
          const y = S.y + dy * p + (dx / len) * 5
          ctx.fillStyle = kind === 1 ? 'rgba(203,213,225,0.7)' : flowColor(cfg, flow)
          ctx.beginPath(); ctx.arc(x, y, kind === 1 ? 2 : 3.3, 0, Math.PI * 2); ctx.fill()
        }
      }

      // nodes
      for (const n of cfg.nodes) {
        const isSel = sel?.kind === 'node' && sel.id === n.id
        ctx.lineWidth = isSel ? 3 : 1.6
        ctx.strokeStyle = isSel ? '#7c9cff' : '#3b4d6e'
        ctx.fillStyle = '#18243a'
        if (n.type === 'router') {
          ctx.beginPath(); ctx.arc(n.x, n.y, 21, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
          ctx.strokeStyle = '#7c9cff'; ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(n.x - 10, n.y); ctx.lineTo(n.x + 10, n.y)
          ctx.moveTo(n.x, n.y - 10); ctx.lineTo(n.x, n.y + 10)
          ctx.moveTo(n.x + 6, n.y - 4); ctx.lineTo(n.x + 10, n.y); ctx.lineTo(n.x + 6, n.y + 4)
          ctx.moveTo(n.x - 6, n.y - 4); ctx.lineTo(n.x - 10, n.y); ctx.lineTo(n.x - 6, n.y + 4)
          ctx.stroke()
        } else {
          roundRect(ctx, n.x - 26, n.y - 16, 52, 32, 7); ctx.fill(); ctx.stroke()
          ctx.fillStyle = '#0b1220'
          roundRect(ctx, n.x - 17, n.y - 9, 34, 18, 3); ctx.fill()
          ctx.fillStyle = '#34d399'
          ctx.fillRect(n.x - 13, n.y - 4, 14, 2); ctx.fillRect(n.x - 13, n.y + 1, 22, 2)
        }
        ctx.fillStyle = '#dbe5f5'
        ctx.font = '600 12px "IBM Plex Sans", sans-serif'
        ctx.textAlign = 'center'
        ctx.fillText(n.label, n.x, n.y + 38)
      }
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [frameRef])

  const toWorld = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    return { x: (e.clientX - r.left) / scaleRef.current, y: (e.clientY - r.top) / scaleRef.current }
  }

  const hit = (x: number, y: number): Selection | null => {
    const cfg = cfgRef.current
    for (const n of cfg.nodes) {
      if (Math.abs(x - n.x) < 30 && Math.abs(y - n.y) < 24) return { kind: 'node', id: n.id }
    }
    const nodes: Record<string, NodeCfg> = {}
    cfg.nodes.forEach((n) => { nodes[n.id] = n })
    let best: Selection | null = null
    let bestD = 11
    for (const l of cfg.links) {
      const A = nodes[l.a]
      const B = nodes[l.b]
      if (!A || !B) continue
      const d = distToSegment(x, y, A.x, A.y, B.x, B.y)
      if (d < bestD) { bestD = d; best = { kind: 'link', id: l.id } }
    }
    return best
  }

  return (
    <div ref={wrapRef} className="w-full">
      <canvas
        ref={canvasRef}
        className="block touch-none rounded-lg bg-ink-950/60"
        onPointerDown={(e) => {
          const { x, y } = toWorld(e)
          const h = hit(x, y)
          onSelect(h)
          if (h?.kind === 'node') {
            dragRef.current = h.id
            e.currentTarget.setPointerCapture(e.pointerId)
          }
        }}
        onPointerMove={(e) => {
          const { x, y } = toWorld(e)
          if (dragRef.current) {
            onMoveNode(dragRef.current, Math.round(Math.min(W - 30, Math.max(30, x))), Math.round(Math.min(H - 40, Math.max(30, y))))
            e.currentTarget.style.cursor = 'grabbing'
          } else {
            const h = hit(x, y)
            e.currentTarget.style.cursor = h ? (h.kind === 'node' ? 'grab' : 'pointer') : 'default'
          }
        }}
        onPointerUp={(e) => {
          dragRef.current = null
          if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
        }}
      />
    </div>
  )
}
