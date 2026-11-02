"""Bottleneck detection and the rule-based Congestion Advisor (no ML / LLM)."""
from __future__ import annotations

import copy
import math


def find_bottleneck(summary):
    """Pick the port that is most responsible for congestion (loss, queueing, utilization)."""
    best, best_score = None, 0.0
    for pid, p in summary["links"].items():
        if p["arrivals"] == 0:
            continue
        score = 3.0 * (p["loss_pct"] or 0) / 100.0 + (p["fill_avg"] or 0) + (p["util_avg"] or 0)
        if score > best_score:
            best, best_score = pid, score
    if best is None:
        return None
    p = summary["links"][best]
    congested = (p["loss_pct"] or 0) > 1.0 or (p["fill_avg"] or 0) > 0.3 or (p["util_avg"] or 0) > 0.9
    return {"port": best, "link": p["link"], "label": p["label"], "util_avg": p["util_avg"], "loss_pct": p["loss_pct"],
            "fill_avg": p["fill_avg"], "congested": bool(congested)}


# ----------------------------------------------------------------------- patches
def apply_patch(config, patch):
    """Return a modified deep copy of a scenario config. Patch ops mirror advisor suggestions."""
    c = copy.deepcopy(config)
    op = patch["op"]
    link = next((l for l in c["links"] if l["id"] == patch.get("link")), None)
    if op == "set_bandwidth":
        link["bandwidth_mbps"] = patch["value"]
    elif op == "set_queue_policy":
        link["queue_policy"] = patch["value"]
        if patch["value"] == "red":
            link["red_min_th"] = link["red_max_th"] = None
    elif op == "set_buffer":
        link["buffer_pkts"] = int(patch["value"])
        link["red_min_th"] = link["red_max_th"] = None
    elif op == "set_tcp_variant":
        for f in c["flows"]:
            if f["kind"] == "tcp":
                f["tcp_variant"] = patch["value"]
    elif op == "scale_burst":
        for e in c["events"]:
            if e["type"] == "burst":
                e["rate_mbps"] = round(e["rate_mbps"] * patch["value"], 3)
    else:
        raise ValueError(f"unknown patch op {op}")
    return c


def nice_up(x):
    """Round a capacity up to a 'real-world' size."""
    steps = [1, 2, 5, 10, 20, 25, 40, 50, 100, 200, 250, 400, 500, 1000, 2000, 2500, 5000, 10000]
    for s in steps:
        if s >= x:
            return float(s)
    return float(math.ceil(x / 1000) * 1000)


# ----------------------------------------------------------------------- advisor
def advise(config, result):
    """Explain congestion from recorded metrics and propose interventions (each carries a patch)."""
    s = result["summary"]
    bn = s["bottleneck"]
    tot = s["totals"]
    if not bn or not bn["congested"]:
        return {"congested": False, "headline": "No significant congestion detected",
                "diagnosis": [{"severity": "ok", "text": "Every link stays below the congestion thresholds "
                                                         "(loss under 1%, queue under 30% full, utilization under 90%)."}],
                "bottleneck": bn, "suggestions": []}
    port = s["links"][bn["port"]]
    link_id = bn["link"]
    cap, offered = port["bandwidth_mbps"], port["offered_mbps"]
    ratio = offered / cap if cap else 0
    util, loss, fill = port["util_avg"], port["loss_pct"], port["fill_avg"]
    reasons = port["drop_reasons"]
    flows_here = [f for f in config["flows"]]
    tcp_flows = [f for f in flows_here if f["kind"] == "tcp"]
    prios = {f["priority"] for f in flows_here}
    has_burst = any(e["type"] == "burst" for e in config["events"])
    has_fail = any(e["type"] == "link_failure" for e in config["events"])
    lname = port["label"]
    diag, sugg = [], []

    diag.append({"severity": "bad", "text": f"Bottleneck: {lname}. It carried {util * 100:.0f}% of its {cap:g} Mbps capacity, "
                                            f"its queue was on average {fill * 100:.0f}% full and {loss:.1f}% of the packets "
                                            f"offered to it were dropped."})
    overload = ratio >= 0.98
    if overload:
        diag.append({"severity": "bad", "text": f"Root cause: sustained overload. About {offered:.1f} Mbps was offered to a "
                                                f"{cap:g} Mbps link (load factor {ratio:.2f}). When arrivals exceed the service "
                                                f"rate, the queue fills and every extra packet must be dropped."})
    elif util < 0.85 and loss > 0.5:
        diag.append({"severity": "warn", "text": f"Root cause: bursts. Average utilization is only {util * 100:.0f}%, yet "
                                                 f"{loss:.1f}% of packets were lost, so short bursts overflow a "
                                                 f"{port['buffer_pkts']}-packet buffer."})
    elif fill > 0.6 and loss < 1.0:
        diag.append({"severity": "warn", "text": f"Root cause: a standing queue (bufferbloat). The buffer stays {fill * 100:.0f}% "
                                                 f"full, so packets wait a long time even though few are dropped."})
    elif tcp_flows:
        diag.append({"severity": "warn", "text": "Root cause: TCP probing for bandwidth. Greedy TCP flows keep increasing "
                                                 "their windows until the buffer overflows, then back off."})
    if tot["delay_avg_ms"] is not None:
        diag.append({"severity": "info", "text": f"Impact: average one-way delay {tot['delay_avg_ms']:.1f} ms (p95 "
                                                 f"{tot['delay_p95_ms']:.1f} ms), jitter {tot['jitter_ms'] or 0:.1f} ms, "
                                                 f"throughput {tot['throughput_mbps']:.2f} Mbps, fairness (Jain) {tot['jain']:.2f}."})
    if reasons.get("link_down") or has_fail:
        diag.append({"severity": "warn", "text": "A link failure event removed capacity or forced traffic onto fewer paths; "
                                                 "that shift adds to the load on this link."})
    if has_burst:
        diag.append({"severity": "warn", "text": "A flash-crowd / DDoS burst injected extra traffic during the run; congestion "
                                                 "is expected to peak while it lasts."})

    if overload:
        new_bw = nice_up(offered * 1.3)
        sugg.append({"id": "add_capacity", "title": f"Raise {lname} capacity from {cap:g} to {new_bw:g} Mbps",
                     "why": f"Capacity must exceed the offered load ({offered:.1f} Mbps) with headroom for bursts.",
                     "expected": "Loss and queueing delay should drop to near zero.",
                     "patch": {"op": "set_bandwidth", "link": link_id, "value": new_bw}})
    if port["policy"] == "droptail" and (fill > 0.4 or tcp_flows):
        sugg.append({"id": "use_red", "title": "Switch the bottleneck queue to RED",
                     "why": "RED drops a few packets early, so senders slow down before the buffer is full. This keeps "
                            "queues (and delay) short and avoids synchronized loss.",
                     "expected": "Lower queueing delay; throughput stays roughly the same.",
                     "patch": {"op": "set_queue_policy", "link": link_id, "value": "red"}})
    if len(prios) > 1 and port["policy"] != "priority":
        sugg.append({"id": "use_priority", "title": "Serve important traffic first with a priority queue",
                     "why": "Flows are tagged with different priority classes. Strict priority protects the high class "
                            "from congestion caused by lower classes (at the cost of starving them).",
                     "expected": "High-priority flows see low delay and loss; low-priority flows absorb the drops.",
                     "patch": {"op": "set_queue_policy", "link": link_id, "value": "priority"}})
    if not overload and util < 0.85 and loss > 0.5:
        nb = port["buffer_pkts"] * 2
        sugg.append({"id": "bigger_buffer", "title": f"Double the buffer to {nb} packets",
                     "why": "Average load is fine; a deeper buffer absorbs short bursts instead of dropping them.",
                     "expected": "Loss from bursts falls; delay may rise slightly.",
                     "patch": {"op": "set_buffer", "link": link_id, "value": nb}})
    if fill > 0.6 and loss < 1.0 and port["buffer_pkts"] > 20:
        nb = max(10, port["buffer_pkts"] // 3)
        sugg.append({"id": "smaller_buffer", "title": f"Shrink the buffer to {nb} packets",
                     "why": "A permanently full buffer only adds delay. A smaller one keeps latency low.",
                     "expected": "Delay and jitter fall substantially.",
                     "patch": {"op": "set_buffer", "link": link_id, "value": nb}})
    if any(f.get("tcp_variant") == "reno" for f in tcp_flows) and util < 0.85:
        sugg.append({"id": "use_cubic", "title": "Use CUBIC instead of Reno for TCP flows",
                     "why": "CUBIC regrows its window faster after a loss on high bandwidth-delay paths, so it fills the "
                            "link better.",
                     "expected": "Higher utilization and goodput.",
                     "patch": {"op": "set_tcp_variant", "value": "cubic"}})
    if has_burst:
        sugg.append({"id": "rate_limit_flood", "title": "Rate-limit the burst source to 10% of its rate",
                     "why": "Policing or filtering the flood at the edge keeps it from filling the bottleneck queue.",
                     "expected": "Legitimate flows recover their throughput and delay.",
                     "patch": {"op": "scale_burst", "value": 0.1}})
    return {"congested": True,
            "headline": f"Congestion at {lname}" + (f": {offered:.1f} Mbps offered vs {cap:g} Mbps capacity" if overload else ""),
            "diagnosis": diag, "bottleneck": bn, "suggestions": sugg}


def key_metrics(summary):
    t = summary["totals"]
    b = summary["bottleneck"]
    return {"throughput_mbps": t["throughput_mbps"], "goodput_mbps": t["goodput_mbps"], "loss_pct": t["loss_pct"],
            "delay_avg_ms": t["delay_avg_ms"], "delay_p95_ms": t["delay_p95_ms"], "jitter_ms": t["jitter_ms"],
            "jain": t["jain"], "bottleneck_util": b["util_avg"] if b else None,
            "bottleneck_fill": b["fill_avg"] if b else None}


def pct_delta(base, v):
    if base is None or v is None:
        return None
    if base == 0:
        return 0.0 if v == 0 else None
    return round((v - base) / abs(base) * 100.0, 2)


def improvement_text(before, after):
    parts = []
    if before["loss_pct"] is not None and after["loss_pct"] is not None and (before["loss_pct"] > 0.05 or after["loss_pct"] > 0.05):
        parts.append(f"loss {before['loss_pct']:.1f}% → {after['loss_pct']:.1f}%")
    if before["delay_avg_ms"] and after["delay_avg_ms"]:
        parts.append(f"average delay {before['delay_avg_ms']:.1f} → {after['delay_avg_ms']:.1f} ms")
    parts.append(f"throughput {before['throughput_mbps']:.2f} → {after['throughput_mbps']:.2f} Mbps")
    return "Measured by re-running the same seed: " + ", ".join(parts) + "."
