import type { ReactNode } from 'react'

export function Num({ label, value, onChange, min, max, step = 1, unit }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; unit?: string
}) {
  return (
    <label className="block">
      <span className="lbl">{label}{unit ? <span className="text-slate-500"> ({unit})</span> : null}</span>
      <input className="input font-mono" type="number" value={Number.isFinite(value) ? value : ''} min={min} max={max} step={step}
        onChange={(e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) onChange(v) }} />
    </label>
  )
}

export function Sel<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  return (
    <label className="block">
      <span className="lbl">{label}</span>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value as T)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )
}

export function Txt({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="lbl">{label}</span>
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      <div className="card-h"><span>{title}</span>{right}</div>
      <div className="px-3.5 pb-3.5">{children}</div>
    </section>
  )
}
