import { useCallback, useEffect, useState } from 'react'
import { get } from './api'
import type { Preset, SimConfig } from './types'
import { FLOW_COLORS, clone, utilColor } from './lib'
import { useSimulation } from './useSimulation'
import TopologyCanvas from './components/TopologyCanvas'
import type { Selection } from './components/TopologyCanvas'
import Controls from './components/Controls'
import Inspector from './components/Inspector'
import Dashboard from './components/Dashboard'
import EventLog from './components/EventLog'
import Advisor from './components/Advisor'
import ScenarioBar from './components/ScenarioBar'
import Timeline from './components/Timeline'
import ExperimentsPage from './components/ExperimentsPage'
import TcpLab from './components/TcpLab'

type Tab = 'sim' | 'exp' | 'tcp'
const TABS: { id: Tab; label: string }[] = [
  { id: 'sim', label: 'Simulator' }, { id: 'exp', label: 'Experiments' }, { id: 'tcp', label: 'TCP Lab' },
]

const STATUS_LABEL: Record<string, string> = {
  idle: 'Ready', connecting: 'Connecting…', running: 'Running live', paused: 'Paused', done: 'Finished', replay: 'Replaying', error: 'Error',
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#111a2b" stroke="#2e4268" />
        <path d="M4 17h6l3-9 5 17 3-8h7" fill="none" stroke="#7c9cff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="leading-tight">
        <div className="text-[17px] font-bold tracking-tight text-white">NetPulse</div>
        <div className="hidden text-[10px] uppercase tracking-[0.16em] text-slate-500 sm:block">Congestion &amp; traffic simulator</div>
      </div>
    </div>
  )
}

export default function App() {
  const sim = useSimulation()
  const [tab, setTab] = useState<Tab>('sim')
  const [presets, setPresets] = useState<Preset[]>([])
  const [config, setConfig] = useState<SimConfig | null>(null)
  const [selected, setSelected] = useState<Selection | null>(null)
  const [speed, setSpeed] = useState(1)
  const [learning, setLearning] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const boot = useCallback(() => {
    setLoadError(null)
    get<Preset[]>('/api/presets')
      .then((p) => { setPresets(p); setConfig((c) => c ?? clone(p[0].config)) })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [])
  useEffect(boot, [boot])

  const loadConfig = useCallback((c: SimConfig) => {
    sim.reset(); setSelected(null); setConfig(clone(c))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.reset])

  const moveNode = useCallback((id: string, x: number, y: number) => {
    setConfig((c) => (c ? { ...c, nodes: c.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)) } : c))
  }, [])

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="card max-w-lg p-6">
          <Logo />
          <h1 className="mt-4 text-lg font-semibold text-white">Can’t reach the NetPulse backend</h1>
          <p className="mt-2 text-sm text-slate-400">{loadError}</p>
          <p className="mt-2 text-sm text-slate-400">Start it with <code className="rounded bg-ink-900 px-1.5 py-0.5 font-mono text-pulse-soft">uvicorn app.main:app --port 8000</code> inside <code className="font-mono">backend/</code> (or run <code className="font-mono">./run.sh</code>), then retry.</p>
          <button className="btn btn-primary mt-4" onClick={boot}>Retry</button>
        </div>
      </div>
    )
  }
  if (!config) {
    return <div className="flex h-full items-center justify-center text-slate-400"><span className="animate-pulse">Loading NetPulse…</span></div>
  }

  const live = sim.status === 'running' || sim.status === 'paused' || sim.status === 'connecting'
  const duration = (sim.usedConfig ?? config).duration_s
  const position = sim.replayT ?? sim.progress * duration
  const dispConfig = sim.usedConfig ?? config

  const onSpeed = (v: number) => { setSpeed(v); sim.setSpeed(v) }

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-ink-600/70 bg-ink-900/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <Logo />
          <nav className="flex gap-1" aria-label="Sections">
            {TABS.map((t) => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition ${tab === t.id ? 'bg-pulse-deep text-white' : 'text-slate-400 hover:bg-ink-700 hover:text-slate-100'}`}>
                {t.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto">
            <ScenarioBar config={config} presets={presets} onLoad={loadConfig} runId={sim.runId} onError={setNotice} />
          </div>
        </div>
      </header>

      {(sim.error || notice) && (
        <div className="mx-auto mt-3 flex w-full max-w-[1800px] items-start justify-between gap-3 rounded-lg border border-bad/40 bg-bad/10 px-4 py-2.5 text-sm text-bad" role="alert">
          <span>{sim.error ?? notice}</span>
          <button className="text-bad/80 hover:text-bad" onClick={() => { sim.dismissError(); setNotice(null) }} aria-label="Dismiss">✕</button>
        </div>
      )}

      <main className="mx-auto w-full max-w-[1800px] flex-1 p-4">
        {tab === 'exp' && <ExperimentsPage presets={presets} current={config} />}
        {tab === 'tcp' && <TcpLab />}
        {tab === 'sim' && (
          <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_350px]">
            <aside className="order-2 space-y-3 lg:order-1">
              <Controls config={config} onChange={setConfig} speed={speed} onSpeed={onSpeed} selected={selected} onSelect={setSelected} />
            </aside>

            <section className="order-1 min-w-0 space-y-4 lg:order-2">
              <div className="card p-3.5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <div>
                    <div className="text-sm font-semibold text-white">{config.name}</div>
                    <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
                      <span className={`h-2 w-2 rounded-full ${sim.status === 'running' ? 'animate-pulse bg-ok' : sim.status === 'error' ? 'bg-bad' : sim.status === 'paused' ? 'bg-warn' : 'bg-slate-500'}`} />
                      {STATUS_LABEL[sim.status]}
                    </div>
                  </div>
                  <div className="ml-auto flex flex-wrap items-center gap-2">
                    {sim.status === 'running' ? (
                      <button className="btn btn-primary" onClick={sim.pause}>⏸ Pause</button>
                    ) : sim.status === 'paused' ? (
                      <button className="btn btn-primary" onClick={sim.resume}>▶ Resume</button>
                    ) : (
                      <button className="btn btn-primary" disabled={sim.status === 'connecting' || sim.busy || config.flows.length === 0}
                        onClick={() => sim.start(config, speed)}>▶ {sim.status === 'done' ? 'Run again' : 'Play live'}</button>
                    )}
                    <button className="btn" onClick={() => { sim.reset() }} disabled={sim.status === 'idle'}>↺ Reset</button>
                    <button className="btn" disabled={live || sim.busy || config.flows.length === 0} onClick={() => sim.runInstant(config)}>
                      {sim.busy ? 'Simulating…' : '⚡ Run instantly'}
                    </button>
                    {sim.status === 'replay'
                      ? <button className="btn" onClick={sim.stopReplay}>⏹ Stop replay</button>
                      : <button className="btn" disabled={!sim.hasFrames} onClick={() => sim.replay(speed)}>⏪ Replay</button>}
                  </div>
                </div>

                <TopologyCanvas config={config} frameRef={sim.frameRef} selected={selected}
                  onSelect={setSelected} onMoveNode={moveNode} />

                <Timeline duration={duration} position={position} markers={sim.view.markers.length ? sim.view.markers : []}
                  scrubbable={sim.hasFrames} onSeek={sim.seek} />

                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-slate-400">
                  <span className="flex items-center gap-1.5">
                    link load
                    <span className="inline-block h-2 w-24 rounded-full" style={{ background: `linear-gradient(90deg, ${utilColor(0)}, ${utilColor(0.65)}, ${utilColor(1)})` }} />
                    0 → 100%
                  </span>
                  <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-bad/80" /> red flash = packet drop</span>
                  <span>bars beside links = queue fill</span>
                  {config.flows.map((f, i) => (
                    <span key={f.id} className="flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-full" style={{ background: FLOW_COLORS[i % FLOW_COLORS.length] }} />{f.label ?? f.id}
                    </span>
                  ))}
                </div>
              </div>

              <Dashboard config={dispConfig} samples={sim.view.samples} markers={sim.view.markers} duration={duration}
                summary={sim.status === 'done' ? sim.summary : null} />
            </section>

            <aside className="order-3 min-w-0 space-y-3">
              <Inspector config={config} selected={selected} onChange={setConfig} onSelect={setSelected} />
              <Advisor config={config} onAdopt={loadConfig} />
              <EventLog events={sim.view.events} learning={learning} onLearning={setLearning} />
            </aside>
          </div>
        )}
      </main>
      <footer className="border-t border-ink-600/50 px-4 py-3 text-center text-[11px] text-slate-600">
        NetPulse · discrete-event packet simulation · seeded &amp; reproducible
      </footer>
    </div>
  )
}
