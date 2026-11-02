"""Framework-independent application logic used by the FastAPI routes (easy to test)."""
from __future__ import annotations

import csv
import io
import json

from . import storage
from .sim.config import ConfigError
from .sim.engine import Simulator
from .sim.experiments import run_advisor, run_experiments, run_tcp_lab, tcp_lab_config
from .sim.presets import get_preset, list_presets

__all__ = ["ConfigError", "simulate", "experiments", "advisor", "tcp_lab", "export_run", "presets",
           "resolve_config", "get_preset", "list_presets"]


def presets():
    return list_presets()


def resolve_config(config, preset):
    if config is not None:
        return config
    return get_preset(preset or "three-sender")


def simulate(config: dict, include_frames=True, frame_dt=0.1) -> dict:
    sim = Simulator(config)
    if include_frames:
        result, frames = sim.run_with_frames(frame_dt)
    else:
        result, frames = sim.run(), None
    run_id = storage.save_run(result)
    out = {"run_id": run_id, **result}
    if frames is not None:
        out["frames"] = frames
    return out


def experiments(config, raised_bandwidth_mbps=None, bottleneck_link=None, policies=("red", "priority")):
    return run_experiments(config, raised_bandwidth_mbps, bottleneck_link, tuple(policies))


def advisor(config, apply_id=None):
    return run_advisor(config, apply_id)


def tcp_lab(**kw):
    cfg = tcp_lab_config(**kw)
    runs = run_tcp_lab(cfg)
    return {"config": cfg, "runs": {v: {"summary": r["summary"], "samples": r["samples"], "events": r["events"]}
                                    for v, r in runs.items()}}


CSV_COLS = ["t", "scope", "id", "throughput_mbps", "goodput_mbps", "delay_avg_ms", "delay_p95_ms", "jitter_ms",
            "loss_pct", "qlen", "util", "cwnd", "jain"]


def export_run(run_id: str, fmt: str):
    """Returns (body, media_type, filename)."""
    run = storage.load_run(run_id)
    if fmt == "json":
        return json.dumps(run, indent=1), "application/json", f"netpulse_{run_id}.json"
    if fmt != "csv":
        raise ValueError("format must be csv or json")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLS, extrasaction="ignore")
    w.writeheader()
    for s in run["samples"]:
        w.writerow({"t": s["t"], "scope": "global", "id": "all", **s["global"]})
        for fid, f in s["flows"].items():
            w.writerow({"t": s["t"], "scope": "flow", "id": fid, **f})
        for pid, l in s["links"].items():
            w.writerow({"t": s["t"], "scope": "link", "id": pid, "throughput_mbps": l["throughput_mbps"],
                        "loss_pct": l["loss_pct"], "qlen": l["qlen"], "util": l["util"]})
    return buf.getvalue(), "text/csv", f"netpulse_{run_id}.csv"
