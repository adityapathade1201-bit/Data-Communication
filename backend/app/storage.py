"""JSON-file storage for scenarios and run results (backend/data, override with NETPULSE_DATA)."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

DATA_DIR = Path(os.environ.get("NETPULSE_DATA", Path(__file__).resolve().parents[1] / "data"))
SAFE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _dir(kind: str) -> Path:
    d = DATA_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check(i: str) -> str:
    if not SAFE.match(i):
        raise KeyError(i)
    return i


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _write(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def save_run(result: dict) -> str:
    run_id = new_id("run")
    _write(_dir("runs") / f"{run_id}.json", {"run_id": run_id, "saved_at": time.time(), **result})
    return run_id


def load_run(run_id: str) -> dict:
    p = _dir("runs") / f"{_check(run_id)}.json"
    if not p.exists():
        raise KeyError(run_id)
    return json.loads(p.read_text(encoding="utf-8"))


def save_scenario(name: str, config: dict) -> dict:
    sid = new_id("sc")
    rec = {"id": sid, "name": name, "saved_at": time.time(), "config": config}
    _write(_dir("scenarios") / f"{sid}.json", rec)
    return rec


def list_scenarios() -> list:
    out = []
    for p in sorted(_dir("scenarios").glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": r["id"], "name": r["name"], "saved_at": r["saved_at"]})
        except (OSError, ValueError, KeyError):
            continue
    return out


def load_scenario(sid: str) -> dict:
    p = _dir("scenarios") / f"{_check(sid)}.json"
    if not p.exists():
        raise KeyError(sid)
    return json.loads(p.read_text(encoding="utf-8"))


def delete_scenario(sid: str) -> None:
    p = _dir("scenarios") / f"{_check(sid)}.json"
    if not p.exists():
        raise KeyError(sid)
    p.unlink()
