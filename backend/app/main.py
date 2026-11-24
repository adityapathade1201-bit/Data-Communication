"""NetPulse API: REST under /api and live simulation streaming over WebSocket (/ws, /ws/simulate)."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import service, storage
from .schemas import (AdvisorRequest, ExperimentRequest, ScenarioSave, SimConfig, SimulateRequest,
                      TcpLabRequest)
from .sim.config import ConfigError
from .sim.engine import Simulator

logger = logging.getLogger("netpulse")

app = FastAPI(title="NetPulse — Network Congestion & Traffic Simulator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRAME_S = 0.05  # one WebSocket frame every 50 ms (20 fps)


def _cfg(config: SimConfig | None, preset: str | None) -> dict:
    try:
        return service.resolve_config(config.to_dict() if config else None, preset)
    except KeyError:
        raise HTTPException(404, f"unknown preset '{preset}'")


def _wrap(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ConfigError as e:
        raise HTTPException(422, str(e))
    except KeyError as e:
        raise HTTPException(404, f"not found: {e.args[0]}")


# ---------------------------------------------------------------------------- REST
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "netpulse", "version": app.version}


@app.get("/api/presets")
def presets():
    return service.presets()


@app.post("/api/simulate")
def simulate(req: SimulateRequest):
    cfg = _cfg(req.config, req.preset)
    sim = Simulator(cfg)
    result = sim.run()
    run_id = storage.save_run(result)
    if not req.include_frames:
        result.pop("frames", None)
    result["run_id"] = run_id
    result["config"] = cfg
    return result


@app.post("/api/experiments/run")
def experiments(req: ExperimentRequest):
    cfg = _cfg(req.config, req.preset)
    return _wrap(service.run_experiments, cfg, req.raised_bandwidth_mbps, req.bottleneck_link, req.policies)


@app.post("/api/advisor")
def advisor(req: AdvisorRequest):
    cfg = _cfg(req.config, req.preset)
    return _wrap(service.advisor, cfg, req.apply)


@app.post("/api/tcp-lab")
def tcp_lab(req: TcpLabRequest):
    return _wrap(service.tcp_lab, req.model_dump())


@app.get("/api/scenarios")
def scenarios():
    return storage.list_scenarios()


@app.post("/api/scenarios")
def save_scenario(req: ScenarioSave):
    return storage.save_scenario(req.name, req.config.to_dict())


@app.get("/api/scenarios/{sid}")
def load_scenario(sid: str):
    return _wrap(storage.load_scenario, sid)


@app.delete("/api/scenarios/{sid}")
def delete_scenario(sid: str):
    _wrap(storage.delete_scenario, sid)
    return {"deleted": sid}


@app.get("/api/export/{run_id}")
def export(run_id: str, format: str = Query("csv", pattern="^(csv|json)$")):
    result = _wrap(storage.load_run, run_id)
    if format == "json":
        import json
        return Response(json.dumps(result), media_type="application/json")
    return Response(service.export_csv(result), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'})


# ----------------------------------------------------------------------------- WebSocket
@app.websocket("/ws")
@app.websocket("/ws/simulate")
async def ws_simulate(ws: WebSocket):
    """Protocol (JSON). Client -> server:
       {"action":"start","config":{...},"speed":1}  {"action":"pause"}  {"action":"resume"}
       {"action":"speed","value":2}  {"action":"stop"}
       Server -> client: started | snapshot | done | error
    """
    await ws.accept()
    inbox: asyncio.Queue = asyncio.Queue()
    TICK = object()

    async def reader():
        try:
            while True:
                await inbox.put(await ws.receive_json())
        except Exception:
            await inbox.put(None)

    reader_task = asyncio.create_task(reader())
    loop = asyncio.get_running_loop()
    sim: Simulator | None = None
    paused, finished, speed = False, False, 1.0
    next_tick = loop.time()
    try:
        while True:
            active = sim is not None and not paused and not finished
            timeout = max(0.0, next_tick - loop.time()) if active else None
            try:
                msg = await asyncio.wait_for(inbox.get(), timeout)
            except asyncio.TimeoutError:
                msg = TICK
            if msg is None:
                break
            if msg is not TICK:
                action = msg.get("action") if isinstance(msg, dict) else None
                if action == "start":
                    try:
                        cfg = SimConfig.model_validate(msg.get("config") or {}).to_dict()
                        sim = Simulator(cfg)
                    except (ValidationError, ConfigError) as e:
                        await ws.send_json({"type": "error", "message": str(e)})
                        sim = None
                        continue
                    speed = float(msg.get("speed", 1.0) or 1.0)
                    paused = finished = False
                    next_tick = loop.time()
                    await ws.send_json({"type": "started", "config": sim.cfg, "duration_s": sim.duration})
                elif action == "pause":
                    paused = True
                elif action == "resume":
                    paused = False
                    next_tick = loop.time()
                elif action == "speed":
                    speed = min(max(float(msg.get("value", 1.0)), 0.05), 50.0)
                elif action == "stop":
                    sim, finished = None, False
                continue
            # --- one simulation frame
            next_tick = loop.time() + FRAME_S
            sim.run_until(sim.now + speed * FRAME_S)
            frame = sim.snapshot()
            frame.update(sim.new_since_last())
            frame["type"] = "snapshot"
            frame["progress"] = round(sim.now / sim.duration, 4)
            await ws.send_json(frame)
            if sim.now >= sim.duration - 1e-9:
                finished = True
                result = sim.finish()
                tail = sim.new_since_last()
                run_id = storage.save_run(result)
                await ws.send_json({"type": "done", "run_id": run_id, "summary": result["summary"], **tail})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        # Do not silently close the socket when a runtime/storage problem occurs.
        # The frontend can now show the real backend error instead of the generic
        # "Connection to the backend was lost" message.
        logger.exception("Unhandled WebSocket simulation failure")
        try:
            await ws.send_json({
                "type": "error",
                "message": f"Backend simulation failed: {type(exc).__name__}: {exc}",
            })
        except Exception:
            pass
    finally:
        reader_task.cancel()


# ----------------------------------------------------------------------------- optional UI hosting
_dist = Path(os.environ.get("NETPULSE_UI", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
