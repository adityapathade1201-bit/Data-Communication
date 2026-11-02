import { useEffect, useRef } from 'react'
import type { LogEvent } from '../types'

const TIPS: Record<string, string> = {
  drop: 'A buffer is a waiting room for packets. When it is full, new arrivals are thrown away — that is a packet drop, and it is how congestion shows up as loss.',
  congestion: 'Congestion means more traffic arrives than a link can send. Packets queue up (delay grows); once the buffer is full they are dropped (loss).',
  tcp: 'TCP treats loss as a signal to slow down: it shrinks its congestion window (cwnd), then grows it again, so the sending rate rises and falls in a sawtooth.',
  event: 'What-if events change the network on purpose (a failed link, a traffic flood) so you can watch how it copes.',
}
const COLORS: Record<string, string> = { info: 'bg-pulse', warn: 'bg-warn', error: 'bg-bad' }

export default function EventLog({ events, learning, onLearning }: { events: LogEvent[]; learning: boolean; onLearning: (v: boolean) => void }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight }, [events.length])
  const shownTip = new Set<string>()
  return (
    <section className="card">
      <div className="card-h">
        <span>Event log</span>
        <label className="flex cursor-pointer items-center gap-1.5 normal-case tracking-normal text-slate-300">
          <input type="checkbox" checked={learning} onChange={(e) => onLearning(e.target.checked)} className="accent-[#7c9cff]" />
          Learning mode
        </label>
      </div>
      <div ref={box} className="max-h-72 space-y-1.5 overflow-y-auto px-3.5 pb-3 text-[13px] leading-snug">
        {events.length === 0 && <p className="text-slate-500">Plain-English commentary appears here while the simulation runs.</p>}
        {events.map((e, i) => {
          const tip = learning && TIPS[e.cat] && !shownTip.has(e.cat)
          if (tip) shownTip.add(e.cat)
          return (
            <div key={i}>
              <div className="flex gap-2">
                <span className={`mt-1.5 h-2 w-2 flex-none rounded-full ${COLORS[e.level] ?? 'bg-pulse'}`} />
                <span className="w-12 flex-none font-mono text-[11px] text-slate-500">{e.t.toFixed(2)}s</span>
                <span className="text-slate-200">{e.msg}</span>
              </div>
              {tip && <div className="ml-[4.6rem] mt-1 rounded-md border border-pulse-deep/40 bg-pulse-deep/10 px-2 py-1.5 text-[12px] text-pulse-soft">💡 {TIPS[e.cat]}</div>}
            </div>
          )
        })}
      </div>
    </section>
  )
}
