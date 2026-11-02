"""Scenario configuration: defaults + validation (plain dicts, no external deps)."""
from __future__ import annotations

import copy
import re

ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")
FLOW_KINDS = ("cbr", "poisson", "bursty", "tcp")
POLICIES = ("droptail", "red", "priority")
TCP_VARIANTS = ("reno", "cubic")


class ConfigError(ValueError):
    pass


def _num(d, key, default, lo=None, hi=None, kind=float):
    v = d.get(key, default)
    if v is None:
        return None if default is None else kind(default)
    try:
        v = kind(v)
    except (TypeError, ValueError):
        raise ConfigError(f"'{key}' must be a number")
    if lo is not None and v < lo:
        raise ConfigError(f"'{key}' must be >= {lo}")
    if hi is not None and v > hi:
        raise ConfigError(f"'{key}' must be <= {hi}")
    return v


def normalize_link(l: dict) -> dict:
    if not ID_RE.match(str(l.get("id", ""))):
        raise ConfigError("link id must match [A-Za-z0-9_.-]{1,32}")
    buf = _num(l, "buffer_pkts", 100, 1, 100000, int)
    policy = l.get("queue_policy", "droptail")
    if policy not in POLICIES:
        raise ConfigError(f"queue_policy must be one of {POLICIES}")
    min_th = l.get("red_min_th")
    max_th = l.get("red_max_th")
    min_th = max(1.0, 0.2 * buf) if min_th is None else float(min_th)
    max_th = max(min_th + 1.0, 0.6 * buf) if max_th is None else float(max_th)
    return {
        "id": str(l["id"]),
        "a": str(l["a"]),
        "b": str(l["b"]),
        "bandwidth_mbps": _num(l, "bandwidth_mbps", 10, 0.001, 1000000),
        "delay_ms": _num(l, "delay_ms", 5, 0, 10000),
        "buffer_pkts": buf,
        "loss_prob": _num(l, "loss_prob", 0, 0, 1),
        "queue_policy": policy,
        "red_min_th": min_th,
        "red_max_th": max_th,
        "red_max_p": _num(l, "red_max_p", 0.1, 0.0001, 1),
        "red_wq": _num(l, "red_wq", 0.02, 0.00001, 1),
    }


def normalize_flow(f: dict) -> dict:
    if not ID_RE.match(str(f.get("id", ""))):
        raise ConfigError("flow id must match [A-Za-z0-9_.-]{1,32}")
    kind = f.get("kind", "cbr")
    if kind not in FLOW_KINDS:
        raise ConfigError(f"flow kind must be one of {FLOW_KINDS}")
    variant = f.get("tcp_variant", "reno")
    if variant not in TCP_VARIANTS:
        raise ConfigError(f"tcp_variant must be one of {TCP_VARIANTS}")
    stop = f.get("stop_s")
    return {
        "id": str(f["id"]),
        "src": str(f["src"]),
        "dst": str(f["dst"]),
        "kind": kind,
        "rate_mbps": _num(f, "rate_mbps", 1.0, 0.0001, 1000000),
        "packet_size": _num(f, "packet_size", 1000, 64, 9000, int),
        "start_s": _num(f, "start_s", 0.0, 0),
        "stop_s": None if stop is None else float(stop),
        "priority": _num(f, "priority", 0, 0, 2, int),
        "burstiness": _num(f, "burstiness", 4.0, 1.0, 100),
        "burst_on_ms": _num(f, "burst_on_ms", 100.0, 1, 100000),
        "tcp_variant": variant,
        "rwnd": _num(f, "rwnd", 256, 4, 100000, int),
        "sack": bool(f.get("sack", True)),
        "label": str(f.get("label", f["id"])),
    }


def normalize_config(cfg: dict) -> dict:
    c = copy.deepcopy(cfg)
    out = {
        "name": str(c.get("name", "scenario")),
        "duration_s": _num(c, "duration_s", 20, 0.5, 600),
        "seed": _num(c, "seed", 1, None, None, int),
        "sample_interval_s": _num(c, "sample_interval_s", 0.25, 0.01, 10),
        "bottleneck_link": c.get("bottleneck_link"),
        "nodes": [],
        "links": [],
        "flows": [],
        "events": [],
    }
    ids = {}
    for n in c.get("nodes", []):
        if not ID_RE.match(str(n.get("id", ""))):
            raise ConfigError("node id must match [A-Za-z0-9_.-]{1,32}")
        if n["id"] in ids:
            raise ConfigError(f"duplicate node id {n['id']}")
        ntype = n.get("type", "host")
        if ntype not in ("host", "router"):
            raise ConfigError("node type must be host or router")
        node = {"id": n["id"], "type": ntype, "label": str(n.get("label", n["id"])),
                "x": float(n.get("x", 0)), "y": float(n.get("y", 0))}
        ids[n["id"]] = node
        out["nodes"].append(node)
    if not out["nodes"]:
        raise ConfigError("scenario needs at least one node")
    link_ids = set()
    for l in c.get("links", []):
        nl = normalize_link(l)
        if nl["id"] in link_ids:
            raise ConfigError(f"duplicate link id {nl['id']}")
        if nl["a"] not in ids or nl["b"] not in ids:
            raise ConfigError(f"link {nl['id']} references an unknown node")
        if nl["a"] == nl["b"]:
            raise ConfigError(f"link {nl['id']} connects a node to itself")
        link_ids.add(nl["id"])
        out["links"].append(nl)
    flow_ids = set()
    for f in c.get("flows", []):
        nf = normalize_flow(f)
        if nf["id"] in flow_ids:
            raise ConfigError(f"duplicate flow id {nf['id']}")
        for end in ("src", "dst"):
            if nf[end] not in ids:
                raise ConfigError(f"flow {nf['id']} {end} '{nf[end]}' is not a node")
            if ids[nf[end]]["type"] != "host":
                raise ConfigError(f"flow {nf['id']} {end} must be a host")
        if nf["src"] == nf["dst"]:
            raise ConfigError(f"flow {nf['id']} has identical src and dst")
        flow_ids.add(nf["id"])
        out["flows"].append(nf)
    for e in c.get("events", []):
        t = e.get("type")
        if t == "link_failure":
            if e.get("link") not in link_ids:
                raise ConfigError("link_failure event references an unknown link")
            dur = e.get("duration")
            out["events"].append({"type": t, "time": _num(e, "time", 5, 0), "link": e["link"],
                                  "duration": None if dur is None else float(dur)})
        elif t == "burst":
            first = out["flows"][0] if out["flows"] else None
            src = e.get("src") or (first["src"] if first else None)
            dst = e.get("dst") or (first["dst"] if first else None)
            if src not in ids or dst not in ids:
                raise ConfigError("burst event needs valid src and dst hosts")
            out["events"].append({
                "type": t, "time": _num(e, "time", 5, 0), "duration": _num(e, "duration", 3, 0.1),
                "rate_mbps": _num(e, "rate_mbps", 20, 0.01), "src": src, "dst": dst,
                "kind": e.get("kind", "cbr") if e.get("kind", "cbr") in ("cbr", "poisson", "bursty") else "cbr",
                "priority": _num(e, "priority", 1, 0, 2, int), "packet_size": _num(e, "packet_size", 1000, 64, 9000, int),
                "label": str(e.get("label", "Flash crowd / DDoS burst"))})
        else:
            raise ConfigError("event type must be link_failure or burst")
    return out
