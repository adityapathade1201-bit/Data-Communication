export type NodeType = 'host' | 'router'
export type Policy = 'droptail' | 'red' | 'priority'
export type FlowKind = 'cbr' | 'poisson' | 'bursty' | 'tcp'

export interface NodeCfg { id: string; type: NodeType; label: string; x: number; y: number }
export interface LinkCfg {
  id: string; a: string; b: string
  bandwidth_mbps: number; delay_ms: number; buffer_pkts: number; loss_prob: number
  queue_policy: Policy
  red_min_th?: number | null; red_max_th?: number | null; red_max_p?: number; red_wq?: number
}
export interface FlowCfg {
  id: string; src: string; dst: string; kind: FlowKind
  rate_mbps: number; packet_size: number; priority: number
  burstiness: number; burst_on_ms: number; tcp_variant: 'reno' | 'cubic'
  start_s?: number; stop_s?: number | null; label?: string
}
export interface EventCfg {
  type: 'link_failure' | 'burst'; time: number; duration?: number | null
  link?: string; rate_mbps?: number; src?: string; dst?: string; priority?: number; label?: string
}
export interface SimConfig {
  name: string; duration_s: number; seed: number; sample_interval_s: number
  bottleneck_link?: string | null
  nodes: NodeCfg[]; links: LinkCfg[]; flows: FlowCfg[]; events: EventCfg[]
}

export interface FlowSample {
  throughput_mbps: number; goodput_mbps: number; sent_mbps: number
  delay_avg_ms: number | null; delay_p95_ms: number | null; jitter_ms: number | null; loss_pct: number
  cwnd?: number; ssthresh?: number; srtt_ms?: number | null
}
export interface LinkSample {
  link: string; util: number; throughput_mbps: number; qlen: number; qavg: number; qmax: number
  fill: number; drops: number; loss_pct: number; up: boolean
}
export interface GlobalSample {
  throughput_mbps: number; goodput_mbps: number; loss_pct: number; delay_avg_ms: number | null
  jain: number; max_util: number; max_fill: number
}
export interface Sample { t: number; flows: Record<string, FlowSample>; links: Record<string, LinkSample>; global: GlobalSample }

/** [portId, fraction along link, 0=data|1=ack, flowId] */
export type PacketDot = [string, number, number, string]
export interface Frame {
  t: number; packets: PacketDot[]; queues: Record<string, number>
  util: Record<string, number>; up: Record<string, boolean>; drops: Record<string, number>
}
export interface LogEvent { t: number; level: 'info' | 'warn' | 'error'; cat: string; msg: string }
export interface Marker { t: number; type: string; label: string }

export interface FlowSummary {
  label: string; kind: FlowKind; src: string; dst: string; priority: number
  sent_pkts: number; delivered_pkts: number; dropped_pkts: number; loss_pct: number
  offered_mbps: number; throughput_mbps: number; goodput_mbps: number
  delay_avg_ms: number | null; delay_p95_ms: number | null; jitter_ms: number | null
  tcp_variant?: string; retransmits?: number; timeouts?: number; fast_retransmits?: number
}
export interface PortSummary {
  link: string; src: string; dst: string; label: string; bandwidth_mbps: number; buffer_pkts: number
  policy: Policy; util_avg: number; throughput_mbps: number; offered_mbps: number; arrivals: number
  drops: number; loss_pct: number; qlen_avg: number; fill_avg: number; drop_reasons: Record<string, number>
}
export interface Totals {
  throughput_mbps: number; goodput_mbps: number; delay_avg_ms: number | null; delay_p95_ms: number | null
  jitter_ms: number | null; loss_pct: number; jain: number; sent_pkts: number; dropped_pkts: number
  packets: { created: number; delivered: number; dropped: number; in_flight: number }
}
export interface Bottleneck {
  port: string; link: string; label: string; util_avg: number; loss_pct: number; fill_avg: number; congested: boolean
}
export interface Summary {
  duration_s: number; flows: Record<string, FlowSummary>; links: Record<string, PortSummary>
  totals: Totals; bottleneck: Bottleneck | null
}
export interface RunResult {
  run_id: string; config: SimConfig; summary: Summary; samples: Sample[]; events: LogEvent[]; markers: Marker[]
  frames?: Frame[]
}

export interface ExperimentOut {
  id: string; name: string; description: string; patch: Record<string, unknown> | null
  summary: Summary; samples: Sample[]; markers: Marker[]
}
export interface CompareRow {
  metric: string; label: string; unit: string; direction: 'higher' | 'lower' | 'info'
  values: Record<string, number | null>; delta_pct: Record<string, number | null>
  flag: Record<string, 'better' | 'worse' | 'neutral'>
}
export interface ExperimentsResult {
  bottleneck_link: string; experiments: ExperimentOut[]; comparison: CompareRow[]; best: string; verdict: string
}

export interface Suggestion { id: string; title: string; why: string; expected: string; patch: Record<string, unknown> }
export interface Advice {
  congested: boolean; headline: string; bottleneck: Bottleneck | null
  diagnosis: { severity: 'ok' | 'info' | 'warn' | 'bad'; text: string }[]
  suggestions: Suggestion[]
}
export interface Applied {
  suggestion: Suggestion; config: SimConfig
  before: Record<string, number | null>; after: Record<string, number | null>
  delta_pct: Record<string, number | null>; text: string; improved: boolean
  after_samples: Sample[]; after_summary: Summary
}
export interface AdvisorResult { advice: Advice; summary: Summary; samples: Sample[]; applied?: Applied }

export interface TcpLabRun { summary: Summary; samples: Sample[]; events: LogEvent[] }
export interface TcpLabResult { config: SimConfig; runs: Record<'reno' | 'cubic', TcpLabRun> }
export interface Preset { id: string; name: string; description: string; config: SimConfig }
export interface ScenarioInfo { id: string; name: string; saved_at: number }
