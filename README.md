# Data Communication — NetPulse Network Congestion & Traffic Simulator

This repository contains **NetPulse**, a network congestion and traffic simulation project for the Data Communication subject. It includes a React + TypeScript frontend, a FastAPI backend, a packet-level discrete-event simulation engine, experiment tools, and automated tests.

## Quick start (Windows)

1. Install Python 3.11+ and Node.js 18+ (including npm).
2. Clone or download this repository.
3. Run `run.bat` from the repository root.
4. Open `http://localhost:5173` in your browser.

For manual setup, Docker instructions, API details, architecture, implemented features, and model assumptions, see below.

---

# NetPulse — Network Congestion & Traffic Simulator

NetPulse creates congestion on purpose, shows **where** the bottleneck is, and **proves with measured simulation results** which fix actually helps. It is a packet-level discrete-event simulator (links, routers, queues, TCP) with a live animated topology, side-by-side experiments, a TCP Reno vs CUBIC lab, and a rule-based Congestion Advisor.

```
3 senders (6 + 5 + 4 = 15 Mbps) ──► Router ──► 10 Mbps bottleneck ──► Receiver
Baseline:  throughput 9.99 Mbps, loss 33.2 %, delay 52 ms
Fix B:     bottleneck 20 Mbps  → loss 0.0 %,  delay 12.6 ms, throughput 14.99 Mbps
```

## Quick start

Requirements: **Python 3.11+**, **Node.js 18+** (npm).

```bash
./run.sh          # macOS / Linux  — installs everything, starts backend + frontend
run.bat           # Windows
```

Then open **http://localhost:5173**. (Backend API/docs: http://localhost:8000/docs)

Manual steps:

```bash
# terminal 1 — backend
cd backend && python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# terminal 2 — frontend
cd frontend && npm install && npm run dev
```

Docker: `docker compose up --build` → UI on :5173, API on :8000.

Tests and a headless demo of the numbers (no web stack needed):

```bash
cd backend
pytest                       # engine tests + API tests
python scripts/sample_run.py # prints the A/B/C comparison table
```

The Vite dev server proxies `/api` and `/ws` to the backend (`VITE_BACKEND_URL` overrides the target), and the backend enables CORS, so it works out of the box.

## Architecture

```
┌────────────────────────── Browser (React + TS + Vite + Tailwind) ──────────────────────────┐
│  App ─┬─ Simulator tab: TopologyCanvas (Canvas) · Controls · Inspector · Dashboard (Recharts)│
│       │                 Advisor · EventLog (learning mode) · Timeline (replay / what-if marks)│
│       ├─ Experiments tab: A/B/C runner · comparison table · overlay charts                    │
│       └─ TCP Lab tab: Reno vs CUBIC (cwnd, queue, goodput)                                    │
│  useSimulation hook: WebSocket client · frame recorder (replay) · REST "run instantly"        │
└───────────────┬───────────────────────────────┬──────────────────────────────────────────────┘
        REST /api/*                       WS /ws/simulate  (snapshots @ 20 fps)
┌───────────────▼───────────────────────────────▼──────────────────────────────────────────────┐
│  FastAPI (app/main.py)  ─ pydantic validation (schemas.py) ─ service.py ─ storage.py (JSON)   │
│                                                                                              │
│  app/sim  (pure standard library, no web dependencies)                                       │
│   config.py     defaults + validation          presets.py   4 one-click scenarios            │
│   engine.py     heapq event loop, Port (queue + serializer + propagation), routing/ECMP,     │
│                 CBR / Poisson / Bursty / TCP Reno+CUBIC, metrics sampler, what-if events      │
│   queues.py     DropTail · RED · strict Priority                                              │
│   analysis.py   bottleneck detection + rule-based advisor (patches)                           │
│   experiments.py A/B/C runner, comparison + % deltas, TCP lab, advisor "apply & re-run"       │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
        backend/data/runs/*.json   backend/data/scenarios/*.json
```

**Simulation model.** Every link direction is a `Port` with an output queue, a transmitter (serialization delay = `size*8/bandwidth`), a propagation pipe (`delay_ms`) and optional random loss. Routing is static shortest-hop with ECMP (stable `crc32` flow hash), recomputed on link failure/restore. A seeded `random.Random(seed)` and a counter-tiebroken heap make runs **bit-for-bit reproducible**.

## REST / WebSocket API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/presets` | 4 presets: 3-sender, office, campus, leaf-spine |
| POST | `/api/simulate` | full run → summary, time series, event log, markers, replay frames (`{"preset":"three-sender"}` or `{"config":{…}}`) |
| POST | `/api/experiments/run` | runs A (baseline), B (bandwidth ×2), C-RED, C-PRIO → comparison table with % deltas + verdict |
| POST | `/api/advisor` | diagnosis + suggestions; with `{"apply":"<suggestion id>"}` applies it, re-runs the same seed and returns before/after |
| POST | `/api/tcp-lab` | Reno vs CUBIC on one bottleneck |
| GET/POST | `/api/scenarios` (+ `GET/DELETE /api/scenarios/{id}`) | save / load scenarios |
| GET | `/api/export/{run_id}?format=csv\|json` | export a finished run |
| WS | `/ws/simulate` (alias `/ws`) | live stream |

WebSocket protocol (JSON): client sends `{"action":"start","config":{…},"speed":1}`, `pause`, `resume`, `{"action":"speed","value":2}`, `stop`. Server sends `started`, a `snapshot` every 50 ms (packet positions, queue sizes, utilization, drops, plus new samples/log events/markers) and finally `done` with the summary and a `run_id` for export.

```bash
curl -s localhost:8000/api/health
curl -s -X POST localhost:8000/api/experiments/run -H 'content-type: application/json' -d '{"preset":"three-sender"}' | python -m json.tool | head -40
```

## What is implemented

- **Engine:** hosts, routers, links (bandwidth, delay, buffer in packets, random loss), flows; DropTail, RED (min/max threshold, max_p, EWMA), strict Priority (3 classes, push-out); CBR, Poisson, bursty on/off, TCP.
- **TCP:** ACK-clocked, RTT estimation + RTO (RFC 6298 style, Karn's rule, backoff), slow start, congestion avoidance, fast retransmit/recovery with SACK, timeout with go-back-N; **Reno** and **CUBIC** (β = 0.7, C = 0.4, TCP-friendly region, fast convergence). `cwnd` is recorded over time.
- **Metrics** (sampled every `sample_interval_s`): per flow and per link — throughput, goodput, average and p95 delay, jitter, loss %, queue length (instant, average, max), utilization; global Jain's fairness index.
- **UI:** draggable topology with click-to-edit nodes/links/flows, live packet animation, queue-fill bars, red drop flashes, green→yellow→red link load, highlighted bottleneck, charts (throughput, delay, loss, queue, utilization, fairness), what-if events on the timeline, learning-mode event log, replay with scrubber, CSV/JSON export, scenario save/load, presets.
- **Experiments:** A/B/C with "Run all", comparison table with % delta (green = better, red = worse) and overlay charts.
- **Advisor:** explains the cause from recorded metrics (overload, bursts, bufferbloat, TCP sawtooth, failure, flood) and offers fixes; **Apply suggestion and re-run** reports the measured improvement.

## Assumptions and limitations

- Packet-level only: no L2/L3 header overhead (ACKs are 40 B), static routing (recomputed instantly on failure; no convergence delay), links are full-duplex and the queue policy/buffer applies to both directions.
- TCP is simplified: greedy bulk transfer, fixed receive window (256 segments), no handshake, no delayed ACKs, no HyStart or pacing. Loss recovery uses SACK (RFC 6675-lite); without SACK a slow-start burst loss collapses into repeated timeouts, which modern stacks avoid. Min RTO is 200 ms (simulation-scale), not 1 s.
- Jain's index uses raw average throughput per flow. Delay is one-way delay of data packets. Flow loss % = data packets dropped / data packets sent (retransmissions included). Link utilization is busy-time based (includes ACKs) and therefore never exceeds 100 %.
- RED's default EWMA weight is 0.02 (faster than the classic 0.002) so it reacts within short runs.
- Priority queueing is strict: the lowest class can starve (visible as high p95 delay in experiment C-PRIO) — that trade-off is intended to be shown.
<<<<<<< HEAD
- Pure-Python engine: 20 s of ~15 Mbps traffic simulates in well under a second (TCP-heavy presets take a few seconds); the leaf-spine/campus presets are scaled-down (Mbps, not Gbps). The live view samples at most 250 in-flight packets per frame.
- One WebSocket run per connection; no authentication (hackathon scope). Run history is stored as JSON files and never pruned.

## Verification status (honest notes)

Built in an offline sandbox with no package installation, so:

- ✅ **Engine, experiments, advisor, storage, export** were executed: 28 engine tests pass (conservation at arbitrary instants and per flow, utilization ≤ 100 %, determinism, baseline ≈ 10 Mbps with drops, experiment B ≈ 0 % loss, TCP, RED, Priority, failure/burst events, advisor).
- ⚠️ **FastAPI layer (`main.py`, `tests/test_api.py`) and the React frontend were not executed here** (FastAPI, pytest, Vite and Recharts could not be installed). The frontend passes a strict `tsc` type-check against stubbed React/Recharts typings, and every API route delegates to code that was run, but please run `pytest` and `npm run build` once on your machine. If anything fails, `python backend/scripts/sample_run.py` still demonstrates the engine results.

## 3–4 minute demo script

1. **(0:00) The problem.** Open the Simulator with the *3-sender bottleneck* preset. "Three senders offer 15 Mbps into a 10 Mbps link." Press **Play live** at 1×.
2. **(0:20) Watch congestion form.** Packets stream along links; the queue bar beside the Router→Receiver link fills; red flashes are drops; the link turns red and is tagged **BOTTLENECK**. Point at the throughput chart flat-lining at 10 Mbps and the loss/delay charts.
3. **(0:50) Learning mode.** In the event log: "Packet dropped: buffer full on Router1 → Receiver link…" with the 💡 explanations.
4. **(1:10) Congestion Advisor.** Click **Analyze**: offered load 15.0 vs capacity 10 Mbps. Click **Apply suggestion and re-run** on *Raise capacity*: loss 33 % → 0 %, delay 52 → 13 ms, measured with the same seed.
5. **(1:50) Experiments tab → Run all.** A baseline, B 20 Mbps, C-RED, C-PRIO. Show the table with % deltas: B wins; RED cuts delay but not loss; Priority protects one sender but starves another (p95 delay 402 ms, fairness drops). "Same traffic, same seed — measured, not guessed."
6. **(2:40) What-if.** Back in the Simulator add a *Flash crowd* (+20 Mbps at 6 s) and a *Link failure*; **Run instantly**. Markers appear on every chart and the timeline; scrub with **Replay**.
7. **(3:10) TCP Lab.** Run Reno vs CUBIC: the cwnd sawtooth, the cubic curve, queue length and goodput.
8. **(3:40) Wrap-up.** Export CSV/JSON, save the scenario; mention determinism (same seed ⇒ identical numbers) and the preset library (office, campus, leaf-spine).

## Repository layout

```
backend/  app/{main,schemas,service,storage}.py  app/sim/{engine,queues,config,analysis,experiments,presets}.py
          tests/{test_engine,test_api}.py  scripts/sample_run.py  data/{runs,scenarios}/
frontend/ src/{App,useSimulation,api,lib,types}.ts(x)  src/components/*.tsx
run.sh  run.bat  docker-compose.yml
```
=======
>>>>>>> 20658d8ad6317aab4c157b09b2586acad296a1c9
