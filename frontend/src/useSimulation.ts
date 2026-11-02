import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { post, wsUrl } from './api'
import type { Frame, LogEvent, Marker, RunResult, Sample, SimConfig, Summary } from './types'

export type SimStatus = 'idle' | 'connecting' | 'running' | 'paused' | 'done' | 'replay' | 'error'
const MAX_FRAMES = 6000

function frameIndex(frames: Frame[], t: number): number {
  let lo = 0
  let hi = frames.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (frames[mid].t <= t) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Owns the live WebSocket run, the REST "instant" run, and replay of the recorded frames. */
export function useSimulation() {
  const [status, setStatus] = useState<SimStatus>('idle')
  const [samples, setSamples] = useState<Sample[]>([])
  const [events, setEvents] = useState<LogEvent[]>([])
  const [markers, setMarkers] = useState<Marker[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [busy, setBusy] = useState(false)
  const [replayT, setReplayT] = useState<number | null>(null)
  const [usedConfig, setUsedConfig] = useState<SimConfig | null>(null)

  const frameRef = useRef<Frame | null>(null)
  const framesRef = useRef<Frame[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<number | undefined>(undefined)
  const doneRef = useRef(false)
  const durationRef = useRef(1)

  const stopTimers = useCallback(() => {
    if (timerRef.current !== undefined) window.clearInterval(timerRef.current)
    timerRef.current = undefined
  }, [])

  const closeWs = useCallback(() => {
    const ws = wsRef.current
    wsRef.current = null
    if (ws) {
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      try { ws.close() } catch { /* already closed */ }
    }
  }, [])

  const clearData = useCallback(() => {
    setSamples([]); setEvents([]); setMarkers([]); setSummary(null); setRunId(null)
    setError(null); setProgress(0); setReplayT(null)
    frameRef.current = null
    framesRef.current = []
    doneRef.current = false
  }, [])

  const reset = useCallback(() => {
    stopTimers(); closeWs(); clearData(); setBusy(false); setStatus('idle'); setUsedConfig(null)
  }, [stopTimers, closeWs, clearData])

  useEffect(() => () => { stopTimers(); closeWs() }, [stopTimers, closeWs])

  const start = useCallback((config: SimConfig, speed: number) => {
    stopTimers(); closeWs(); clearData()
    setStatus('connecting')
    let ws: WebSocket
    try {
      ws = new WebSocket(wsUrl())
    } catch {
      setError('Could not open a WebSocket connection to the backend.'); setStatus('error'); return
    }
    wsRef.current = ws
    let lastProgress = 0
    ws.onopen = () => ws.send(JSON.stringify({ action: 'start', config, speed }))
    ws.onmessage = (ev: MessageEvent) => {
      const m = JSON.parse(String(ev.data))
      if (m.type === 'started') {
        durationRef.current = m.duration_s
        setUsedConfig(m.config as SimConfig)
        setStatus('running')
      } else if (m.type === 'snapshot') {
        frameRef.current = m as Frame
        if (framesRef.current.length < MAX_FRAMES) {
          framesRef.current.push({ t: m.t, packets: m.packets, queues: m.queues, util: m.util, up: m.up, drops: m.drops })
        }
        if (m.samples?.length) setSamples((p) => p.concat(m.samples))
        if (m.events?.length) setEvents((p) => p.concat(m.events))
        if (m.markers?.length) setMarkers((p) => p.concat(m.markers))
        if (m.progress - lastProgress >= 0.004) { lastProgress = m.progress; setProgress(m.progress) }
      } else if (m.type === 'done') {
        doneRef.current = true
        if (m.samples?.length) setSamples((p) => p.concat(m.samples))
        if (m.events?.length) setEvents((p) => p.concat(m.events))
        if (m.markers?.length) setMarkers((p) => p.concat(m.markers))
        setSummary(m.summary as Summary); setRunId(m.run_id as string); setProgress(1); setStatus('done')
        closeWs()
      } else if (m.type === 'error') {
        setError(String(m.message)); setStatus('error'); closeWs()
      }
    }
    ws.onerror = () => { setError('Could not reach the simulation backend over WebSocket. Is it running on port 8000?'); setStatus('error') }
    ws.onclose = () => {
      if (!doneRef.current) { setError((e) => e ?? 'Connection to the backend was lost.'); setStatus('error') }
    }
  }, [stopTimers, closeWs, clearData])

  const send = useCallback((msg: unknown) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
  }, [])
  const pause = useCallback(() => { send({ action: 'pause' }); setStatus('paused') }, [send])
  const resume = useCallback(() => { send({ action: 'resume' }); setStatus('running') }, [send])
  const setSpeed = useCallback((value: number) => send({ action: 'speed', value }), [send])

  /** One-shot run through POST /api/simulate (no live streaming; frames returned for replay). */
  const runInstant = useCallback(async (config: SimConfig) => {
    stopTimers(); closeWs(); clearData(); setBusy(true)
    try {
      const r = await post<RunResult>('/api/simulate', { config, include_frames: true })
      framesRef.current = r.frames ?? []
      frameRef.current = framesRef.current[framesRef.current.length - 1] ?? null
      setSamples(r.samples); setEvents(r.events); setMarkers(r.markers); setSummary(r.summary)
      setRunId(r.run_id); setUsedConfig(r.config); setProgress(1); setStatus('done')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setStatus('error')
    } finally {
      setBusy(false)
    }
  }, [stopTimers, closeWs, clearData])

  const hasFrames = status === 'done' || status === 'replay'

  const seek = useCallback((t: number) => {
    const frames = framesRef.current
    if (!frames.length) return
    stopTimers()
    frameRef.current = frames[frameIndex(frames, t)]
    setReplayT(t); setStatus('replay')
  }, [stopTimers])

  const replay = useCallback((speed: number) => {
    const frames = framesRef.current
    if (!frames.length) return
    stopTimers()
    const end = frames[frames.length - 1].t
    let t = 0
    let tick = 0
    setStatus('replay'); setReplayT(0)
    timerRef.current = window.setInterval(() => {
      t += 0.05 * speed
      if (t >= end) {
        stopTimers()
        frameRef.current = frames[frames.length - 1]
        setReplayT(null); setStatus('done')
        return
      }
      frameRef.current = frames[frameIndex(frames, t)]
      tick += 1
      if (tick % 3 === 0) setReplayT(t)
    }, 50)
  }, [stopTimers])

  const stopReplay = useCallback(() => {
    stopTimers(); setReplayT(null); setStatus('done')
    const f = framesRef.current
    frameRef.current = f.length ? f[f.length - 1] : null
  }, [stopTimers])

  const view = useMemo(() => {
    if (replayT === null) return { samples, events, markers }
    return {
      samples: samples.filter((s) => s.t <= replayT),
      events: events.filter((e) => e.t <= replayT),
      markers: markers.filter((m) => m.t <= replayT),
    }
  }, [samples, events, markers, replayT])

  const framesEnd = framesRef.current.length ? framesRef.current[framesRef.current.length - 1].t : 0

  return {
    status, error, busy, progress, runId, summary, usedConfig, frameRef, view, replayT, hasFrames, framesEnd,
    fullSamples: samples, start, pause, resume, setSpeed, reset, runInstant, replay, seek, stopReplay,
    dismissError: () => setError(null),
  }
}
