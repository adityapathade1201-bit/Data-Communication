"""Experiment runner: A (baseline), B (more bandwidth), C (queue policies) + comparison table."""
from __future__ import annotations

import copy

from .analysis import advise, apply_patch, improvement_text, key_metrics, pct_delta
from .engine import Simulator

METRICS = [
    ("throughput_mbps", "Throughput", "Mbps", "higher"),
    ("goodput_mbps", "Goodput", "Mbps", "higher"),
    ("loss_pct", "Packet loss", "%", "lower"),
    ("delay_avg_ms", "Average delay", "ms", "lower"),
    ("delay_p95_ms", "p95 delay", "ms", "lower"),
    ("jitter_ms", "Jitter", "ms", "lower"),
    ("jain", "Fairness (Jain)", "", "higher"),
    ("bottleneck_util", "Bottleneck utilization", "", "info"),
    ("bottleneck_fill", "Avg queue fill", "", "lower"),
]


def run_config(cfg):
    return Simulator(cfg).run()


def _verdict_flag(direction, delta):
    if delta is None or direction == "info" or abs(delta) < 1.0:
        return "neutral"
    good = delta > 0 if direction == "higher" else delta < 0
    return "better" if good else "worse"


def compare(results):
    """results: ordered {id: run result}. First entry is the baseline."""
    ids = list(results)
    base = ids[0]
    km = {i: key_metrics(results[i]["summary"]) for i in ids}
    rows = []
    for key, label, unit, direction in METRICS:
        row = {"metric": key, "label": label, "unit": unit, "direction": direction,
               "values": {i: km[i][key] for i in ids}, "delta_pct": {}, "flag": {}}
        for i in ids[1:]:
            d = pct_delta(km[base][key], km[i][key])
            row["delta_pct"][i] = d
            row["flag"][i] = _verdict_flag(direction, d)
        rows.append(row)
    return rows


def run_experiments(base_cfg, raised_bandwidth_mbps=None, bottleneck_link=None, policies=("red", "priority")):
    base_run = run_config(base_cfg)
    bn = base_run["summary"]["bottleneck"]
    link_id = bottleneck_link or base_cfg.get("bottleneck_link") or (bn["link"] if bn else base_cfg["links"][0]["id"])
    link = next(l for l in base_run["config"]["links"] if l["id"] == link_id)
    new_bw = raised_bandwidth_mbps or link["bandwidth_mbps"] * 2
    specs = [("A", "Baseline", f"Current setup: {link['bandwidth_mbps']:g} Mbps bottleneck, {link['queue_policy']} queue.", None)]
    specs.append(("B", "More bandwidth", f"Same traffic, bottleneck raised to {new_bw:g} Mbps.",
                  {"op": "set_bandwidth", "link": link_id, "value": new_bw}))
    names = {"red": "RED", "priority": "Priority", "droptail": "DropTail"}
    for p in policies:
        specs.append((f"C-{p.upper()[:4]}", f"Queue: {names[p]}", f"Same traffic, bottleneck queue changed to {names[p]}.",
                      {"op": "set_queue_policy", "link": link_id, "value": p}))
    results, exps = {}, []
    for eid, name, desc, patch in specs:
        res = base_run if patch is None else run_config(apply_patch(base_cfg, patch))
        results[eid] = res
        exps.append({"id": eid, "name": name, "description": desc, "patch": patch,
                     "summary": res["summary"], "samples": res["samples"], "markers": res["markers"]})
    rows = compare(results)
    best = min(results, key=lambda i: (results[i]["summary"]["totals"]["loss_pct"] or 0,
                                       results[i]["summary"]["totals"]["delay_avg_ms"] or 0))
    bm, bs = key_metrics(results[best]["summary"]), key_metrics(base_run["summary"])
    verdict = (f"Experiment {best} ({next(e['name'] for e in exps if e['id'] == best)}) performed best: "
               + improvement_text(bs, bm)) if best != "A" else "No variation beat the baseline."
    return {"bottleneck_link": link_id, "experiments": exps, "comparison": rows, "best": best, "verdict": verdict}


def run_tcp_lab(base_cfg):
    """Reno vs CUBIC on the same dumbbell: the TCP flows' variant is switched, nothing else changes."""
    out = {}
    for variant in ("reno", "cubic"):
        cfg = copy.deepcopy(base_cfg)
        for f in cfg["flows"]:
            f["tcp_variant"] = variant
        out[variant] = run_config(cfg)
    return out


def tcp_lab_config(bandwidth_mbps=10, delay_ms=20, buffer_pkts=50, flows=1, duration_s=30, seed=1, policy="droptail"):
    nodes = [{"id": "R1", "type": "router", "label": "Router1", "x": 380, "y": 280},
             {"id": "R2", "type": "router", "label": "Router2", "x": 620, "y": 280},
             {"id": "D", "type": "host", "label": "Receiver", "x": 900, "y": 280}]
    links = [{"id": "LBN", "a": "R1", "b": "R2", "bandwidth_mbps": bandwidth_mbps, "delay_ms": delay_ms,
              "buffer_pkts": buffer_pkts, "queue_policy": policy},
             {"id": "LR", "a": "R2", "b": "D", "bandwidth_mbps": 100, "delay_ms": 1, "buffer_pkts": 200}]
    fl = []
    for i in range(flows):
        y = 280 + (i - (flows - 1) / 2) * 120
        nodes.append({"id": f"H{i + 1}", "type": "host", "label": f"Sender {i + 1}", "x": 90, "y": y})
        links.append({"id": f"LH{i + 1}", "a": f"H{i + 1}", "b": "R1", "bandwidth_mbps": 100, "delay_ms": 1, "buffer_pkts": 200})
        fl.append({"id": f"tcp{i + 1}", "src": f"H{i + 1}", "dst": "D", "kind": "tcp", "label": f"TCP flow {i + 1}",
                   "start_s": 0.1 * i})
    return {"name": "TCP lab", "duration_s": duration_s, "seed": seed, "sample_interval_s": 0.1, "bottleneck_link": "LBN",
            "nodes": nodes, "links": links, "flows": fl, "events": []}


def run_advisor(config, apply_id=None):
    before = run_config(config)
    adv = advise(before["config"], before)
    out = {"advice": adv, "summary": before["summary"], "samples": before["samples"]}
    if apply_id:
        sug = next((s for s in adv["suggestions"] if s["id"] == apply_id), None)
        if sug is None:
            raise KeyError(apply_id)
        patched = apply_patch(before["config"], sug["patch"])
        after = run_config(patched)
        kb, ka = key_metrics(before["summary"]), key_metrics(after["summary"])
        out["applied"] = {
            "suggestion": sug, "config": patched, "before": kb, "after": ka,
            "delta_pct": {k: pct_delta(kb[k], ka[k]) for k in kb},
            "text": improvement_text(kb, ka), "after_samples": after["samples"], "after_summary": after["summary"],
            "improved": (ka["loss_pct"] or 0) < (kb["loss_pct"] or 0) - 0.05
                        or (ka["delay_avg_ms"] or 0) < (kb["delay_avg_ms"] or 0) * 0.95}
    return out
