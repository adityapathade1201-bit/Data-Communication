import type { LinkCfg, SimConfig } from './types'

export const FLOW_COLORS = ['#7c9cff', '#34d399', '#f59e0b', '#f472b6', '#22d3ee', '#a78bfa', '#fb923c', '#a3e635']
export const EXP_COLORS: Record<string, string> = { A: '#94a3b8', B: '#34d399', 'C-RED': '#f59e0b', 'C-PRIO': '#a78bfa' }

export function flowColor(config: SimConfig, id: string): string {
  const i = config.flows.findIndex((f) => f.id === id)
  return i >= 0 ? FLOW_COLORS[i % FLOW_COLORS.length] : '#ef4444'
}

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v))

/** green -> yellow -> red by utilization (0..1) */
export function utilColor(u: number): string {
  const t = clamp((u - 0.4) / 0.55)
  return `hsl(${Math.round(140 * (1 - t))} 78% 52%)`
}

export function fmt(v: number | null | undefined, d = 2): string {
  return v === null || v === undefined || Number.isNaN(v) ? '–' : v.toFixed(d)
}

export function clone<T>(o: T): T {
  return JSON.parse(JSON.stringify(o)) as T
}

export function portIds(l: LinkCfg): [string, string] {
  return [`${l.a}>${l.b}`, `${l.b}>${l.a}`]
}

/** Configured bottleneck link, else the slowest link. */
export function bottleneckLinkId(c: SimConfig): string | undefined {
  if (c.bottleneck_link && c.links.some((l) => l.id === c.bottleneck_link)) return c.bottleneck_link
  return [...c.links].sort((a, b) => a.bandwidth_mbps - b.bandwidth_mbps)[0]?.id
}

export function uid(prefix: string, taken: string[]): string {
  let i = 1
  while (taken.includes(`${prefix}${i}`)) i++
  return `${prefix}${i}`
}

export function downloadUrl(runId: string, format: 'csv' | 'json'): string {
  return `/api/export/${runId}?format=${format}`
}
