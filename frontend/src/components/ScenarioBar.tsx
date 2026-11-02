import { useCallback, useEffect, useState } from 'react'
import { get, post } from '../api'
import type { Preset, ScenarioInfo, SimConfig } from '../types'
import { downloadUrl } from '../lib'

interface Props {
  config: SimConfig
  presets: Preset[]
  onLoad: (c: SimConfig) => void
  runId: string | null
  onError: (msg: string) => void
}

export default function ScenarioBar({ config, presets, onLoad, runId, onError }: Props) {
  const [saved, setSaved] = useState<ScenarioInfo[]>([])
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    get<ScenarioInfo[]>('/api/scenarios').then(setSaved).catch(() => setSaved([]))
  }, [])
  useEffect(refresh, [refresh])

  const save = async () => {
    const name = window.prompt('Name this scenario', config.name)
    if (!name) return
    setBusy(true)
    try {
      await post('/api/scenarios', { name, config: { ...config, name } })
      refresh()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const load = async (id: string) => {
    if (!id) return
    try {
      const rec = await get<{ config: SimConfig }>(`/api/scenarios/${id}`)
      onLoad(rec.config)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className="input w-auto" aria-label="Preset" value="" onChange={(e) => { const p = presets.find((x) => x.id === e.target.value); if (p) onLoad(p.config) }}>
        <option value="">Presets…</option>
        {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <select className="input w-auto" aria-label="Saved scenarios" value="" onChange={(e) => load(e.target.value)}>
        <option value="">Load saved ({saved.length})…</option>
        {saved.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <button className="btn btn-sm" onClick={save} disabled={busy}>Save</button>
      <a className={`btn btn-sm ${runId ? '' : 'pointer-events-none opacity-40'}`} href={runId ? downloadUrl(runId, 'csv') : undefined} download>CSV</a>
      <a className={`btn btn-sm ${runId ? '' : 'pointer-events-none opacity-40'}`} href={runId ? downloadUrl(runId, 'json') : undefined} download>JSON</a>
    </div>
  )
}
