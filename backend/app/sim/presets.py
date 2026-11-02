"""One-click scenario presets. Canvas coordinates live in a 1000 x 560 space."""
from __future__ import annotations

import copy


def _host(i, label, x, y):
    return {"id": i, "type": "host", "label": label, "x": x, "y": y}


def _router(i, label, x, y):
    return {"id": i, "type": "router", "label": label, "x": x, "y": y}


def _link(i, a, b, bw, delay, buf=100, **kw):
    d = {"id": i, "a": a, "b": b, "bandwidth_mbps": bw, "delay_ms": delay, "buffer_pkts": buf}
    d.update(kw)
    return d


def _flow(i, src, dst, kind, rate=1.0, label=None, **kw):
    d = {"id": i, "src": src, "dst": dst, "kind": kind, "rate_mbps": rate, "label": label or i}
    d.update(kw)
    return d


def three_sender():
    return {
        "name": "3-sender bottleneck", "duration_s": 20, "seed": 1, "sample_interval_s": 0.25, "bottleneck_link": "LBN",
        "nodes": [_host("A", "Sender A", 90, 110), _host("B", "Sender B", 90, 280), _host("C", "Sender C", 90, 450),
                  _router("R1", "Router1", 430, 280), _host("S", "Receiver", 900, 280)],
        "links": [_link("LA", "A", "R1", 100, 2), _link("LB", "B", "R1", 100, 2), _link("LC", "C", "R1", 100, 2),
                  _link("LBN", "R1", "S", 10, 10, 50)],
        "flows": [_flow("fA", "A", "S", "cbr", 6, "Sender A (6 Mbps)", priority=2),
                  _flow("fB", "B", "S", "cbr", 5, "Sender B (5 Mbps)", priority=1),
                  _flow("fC", "C", "S", "cbr", 4, "Sender C (4 Mbps)", priority=0)],
        "events": []}


def office():
    return {
        "name": "Office network", "duration_s": 15, "seed": 3, "sample_interval_s": 0.25, "bottleneck_link": "UPLINK",
        "nodes": [_host("PC1", "PC 1", 90, 90), _host("PC2", "PC 2", 90, 230), _host("PC3", "PC 3", 90, 370),
                  _host("CAM", "Video call", 90, 500), _router("SW", "Office switch", 360, 290),
                  _router("GW", "Gateway", 560, 290), _router("ISP", "ISP", 740, 290), _host("CLOUD", "Cloud", 930, 290)],
        "links": [_link("L1", "PC1", "SW", 100, 1), _link("L2", "PC2", "SW", 100, 1), _link("L3", "PC3", "SW", 100, 1),
                  _link("L4", "CAM", "SW", 100, 1), _link("L5", "SW", "GW", 100, 1),
                  _link("UPLINK", "GW", "ISP", 20, 5, 100), _link("L7", "ISP", "CLOUD", 100, 15)],
        "flows": [_flow("backup", "PC1", "CLOUD", "tcp", label="PC 1 cloud backup (CUBIC)", tcp_variant="cubic", priority=2),
                  _flow("upload", "PC2", "CLOUD", "tcp", label="PC 2 file upload (Reno)", tcp_variant="reno", priority=2),
                  _flow("web", "PC3", "CLOUD", "poisson", 3, "PC 3 web traffic (3 Mbps)", priority=1),
                  _flow("call", "CAM", "CLOUD", "cbr", 4, "Video call (4 Mbps)", priority=0, packet_size=1200)],
        "events": []}


def campus():
    return {
        "name": "College campus", "duration_s": 15, "seed": 7, "sample_interval_s": 0.25, "bottleneck_link": "UPLINK",
        "nodes": [_host("LAB", "Computer lab", 80, 90), _host("HOSTEL", "Hostel Wi-Fi", 80, 280), _host("LIB", "Library", 80, 470),
                  _router("CORE", "Core switch", 360, 280), _host("SRV", "Campus server", 560, 90),
                  _router("GW", "Gateway", 600, 280), _host("NET", "Internet", 910, 280)],
        "links": [_link("L1", "LAB", "CORE", 100, 1), _link("L2", "HOSTEL", "CORE", 100, 1), _link("L3", "LIB", "CORE", 100, 1),
                  _link("L4", "CORE", "SRV", 100, 1), _link("L5", "CORE", "GW", 100, 1),
                  _link("UPLINK", "GW", "NET", 20, 8, 80)],
        "flows": [_flow("lab", "LAB", "NET", "tcp", label="Lab downloads (CUBIC)", tcp_variant="cubic"),
                  _flow("hostel", "HOSTEL", "NET", "bursty", 8, "Hostel video streams (8 Mbps avg)", burstiness=4, burst_on_ms=150),
                  _flow("lib", "LIB", "NET", "poisson", 4, "Library browsing (4 Mbps)"),
                  _flow("lan", "LIB", "SRV", "cbr", 8, "Library to campus server (8 Mbps)")],
        "events": []}


def leaf_spine():
    nodes = [_router("SP1", "Spine 1", 300, 80), _router("SP2", "Spine 2", 700, 80),
             _router("LF1", "Leaf 1", 150, 290), _router("LF2", "Leaf 2", 500, 290), _router("LF3", "Leaf 3", 850, 290)]
    xs = [60, 240, 410, 590, 760, 940]
    for i, x in enumerate(xs, 1):
        nodes.append(_host(f"S{i}", f"Server {i}", x, 490))
    links = []
    for i in range(6):
        links.append(_link(f"A{i + 1}", f"S{i + 1}", f"LF{i // 2 + 1}", 10, 0.1, 100))
    for lf in (1, 2, 3):
        for sp in (1, 2):
            links.append(_link(f"U{lf}{sp}", f"LF{lf}", f"SP{sp}", 10, 0.2, 100))
    return {
        "name": "Data-center leaf-spine", "duration_s": 12, "seed": 5, "sample_interval_s": 0.25,
        "nodes": nodes, "links": links,
        "flows": [_flow("f1", "S1", "S3", "cbr", 7, "S1 → S3 (7 Mbps)"),
                  _flow("f2", "S2", "S4", "cbr", 7, "S2 → S4 (7 Mbps)"),
                  _flow("f3", "S1", "S5", "poisson", 3, "S1 → S5 (3 Mbps)"),
                  _flow("f4", "S2", "S6", "bursty", 3, "S2 → S6 (3 Mbps avg)", burstiness=3),
                  _flow("f5", "S3", "S5", "tcp", label="S3 → S5 TCP (CUBIC)", tcp_variant="cubic", start_s=0.5)],
        "events": []}


PRESETS = {
    "three-sender": ("3-sender bottleneck", "Senders A/B/C offer 15 Mbps into a 10 Mbps bottleneck.", three_sender),
    "office": ("Office network", "TCP backups, web traffic and a video call share a 20 Mbps uplink.", office),
    "campus": ("College campus", "Lab, hostel and library share a 20 Mbps campus uplink.", campus),
    "leaf-spine": ("Data-center leaf-spine", "Two spines, three leaves; ECMP spreads flows over uplinks.", leaf_spine),
}


def list_presets():
    return [{"id": k, "name": v[0], "description": v[1], "config": v[2]()} for k, v in PRESETS.items()]


def get_preset(pid):
    if pid not in PRESETS:
        raise KeyError(pid)
    return copy.deepcopy(PRESETS[pid][2]())
