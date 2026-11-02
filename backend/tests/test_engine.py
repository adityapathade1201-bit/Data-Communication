"""Engine tests: conservation, utilization bound, determinism and sanity checks."""
import copy
import json

import pytest

from app.sim.analysis import advise, apply_patch
from app.sim.config import ConfigError, normalize_config
from app.sim.engine import Simulator
from app.sim.experiments import run_advisor, run_experiments, tcp_lab_config
from app.sim.presets import get_preset, list_presets


def run(cfg):
    return Simulator(cfg).run()


@pytest.fixture(scope="module")
def baseline():
    return run(get_preset("three-sender"))


def test_packet_conservation_at_end_of_run(baseline):
    p = baseline["summary"]["totals"]["packets"]
    assert p["created"] == p["delivered"] + p["dropped"] + p["in_flight"]
    assert p["dropped"] > 0


@pytest.mark.parametrize("preset", ["three-sender", "office", "campus", "leaf-spine"])
def test_conservation_mid_run_and_per_flow(preset):
    """sent = delivered + dropped + in-flight must hold at arbitrary instants, for every flow too."""
    sim = Simulator(get_preset(preset))
    for t in (0.37, 1.9, 4.123, 7.77):
        sim.run_until(t)
        c = sim.conservation()
        assert c["created"] == c["delivered"] + c["dropped"] + c["in_flight"]
        in_flight = {}
        for port in sim.ports.values():
            pkts = port.queue.packets() + [v[0] for v in port.prop.values()] + ([port.tx_pkt] if port.tx_pkt else [])
            for pkt in pkts:
                in_flight[pkt.flow] = in_flight.get(pkt.flow, 0) + 1
        for fid, fl in sim.flows.items():
            assert fl.created == fl.delivered + fl.dropped + in_flight.get(fid, 0)


@pytest.mark.parametrize("preset", ["three-sender", "campus", "leaf-spine"])
def test_utilization_never_exceeds_100_percent(preset):
    res = run(get_preset(preset))
    for s in res["samples"]:
        for link in s["links"].values():
            assert 0.0 <= link["util"] <= 1.0
            assert link["throughput_mbps"] <= next(
                l["bandwidth_mbps"] for l in res["config"]["links"] if l["id"] == link["link"]) + 1e-6
    for port in res["summary"]["links"].values():
        assert port["util_avg"] <= 1.0


def test_determinism_same_seed_identical_results():
    a, b = run(get_preset("campus")), run(get_preset("campus"))
    assert json.dumps(a["summary"], sort_keys=True) == json.dumps(b["summary"], sort_keys=True)
    assert json.dumps(a["samples"], sort_keys=True) == json.dumps(b["samples"], sort_keys=True)


def test_different_seed_changes_random_traffic():
    cfg = get_preset("campus")
    other = copy.deepcopy(cfg)
    other["seed"] = cfg["seed"] + 1
    assert run(cfg)["summary"]["totals"] != run(other)["summary"]["totals"]


def test_baseline_throughput_caps_near_bottleneck_with_drops(baseline):
    t = baseline["summary"]["totals"]
    assert 9.0 <= t["throughput_mbps"] <= 10.2
    assert 25.0 <= t["loss_pct"] <= 40.0  # (15 - 10) / 15 = 33%
    bn = baseline["summary"]["bottleneck"]
    assert bn["link"] == "LBN" and bn["congested"] and bn["util_avg"] > 0.97


def test_experiment_b_has_near_zero_loss():
    cfg = get_preset("three-sender")
    cfg["links"][3]["bandwidth_mbps"] = 20
    t = run(cfg)["summary"]["totals"]
    assert t["loss_pct"] < 0.5
    assert t["throughput_mbps"] > 14.5


def test_experiments_endpoint_logic():
    out = run_experiments(get_preset("three-sender"))
    ids = [e["id"] for e in out["experiments"]]
    assert ids == ["A", "B", "C-RED", "C-PRIO"]
    assert out["best"] == "B"
    loss = next(r for r in out["comparison"] if r["metric"] == "loss_pct")
    assert loss["delta_pct"]["B"] <= -90
    red_delay = next(r for r in out["comparison"] if r["metric"] == "delay_avg_ms")
    assert red_delay["delta_pct"]["C-RED"] < 0  # RED keeps the queue shorter than DropTail


def test_serialization_and_propagation_delay_on_idle_path():
    cfg = {"duration_s": 3, "nodes": [{"id": "A", "type": "host"}, {"id": "B", "type": "host"}],
           "links": [{"id": "L", "a": "A", "b": "B", "bandwidth_mbps": 8, "delay_ms": 10, "buffer_pkts": 50}],
           "flows": [{"id": "f", "src": "A", "dst": "B", "kind": "cbr", "rate_mbps": 0.5, "packet_size": 1000}]}
    d = run(cfg)["summary"]["flows"]["f"]
    # 1000 B * 8 / 8 Mbps = 1 ms serialization + 10 ms propagation
    assert d["delay_avg_ms"] == pytest.approx(11.0, abs=0.01)
    assert d["loss_pct"] == 0


def test_random_loss_is_applied():
    cfg = {"duration_s": 10, "nodes": [{"id": "A", "type": "host"}, {"id": "B", "type": "host"}],
           "links": [{"id": "L", "a": "A", "b": "B", "bandwidth_mbps": 100, "delay_ms": 1, "loss_prob": 0.1}],
           "flows": [{"id": "f", "src": "A", "dst": "B", "kind": "poisson", "rate_mbps": 4, "packet_size": 1000}]}
    assert run(cfg)["summary"]["flows"]["f"]["loss_pct"] == pytest.approx(10.0, abs=1.5)


def test_red_keeps_queue_shorter_than_droptail():
    dt = get_preset("office")
    red = copy.deepcopy(dt)
    next(l for l in red["links"] if l["id"] == "UPLINK")["queue_policy"] = "red"
    a, b = run(dt)["summary"]["links"]["GW>ISP"], run(red)["summary"]["links"]["GW>ISP"]
    assert b["qlen_avg"] < a["qlen_avg"]
    assert "red_early" in b["drop_reasons"] or "red_forced" in b["drop_reasons"]


def test_priority_queue_protects_high_class():
    cfg = get_preset("three-sender")
    cfg["links"][3]["queue_policy"] = "priority"
    f = run(cfg)["summary"]["flows"]
    assert f["fC"]["loss_pct"] < 0.5 and f["fA"]["loss_pct"] > 50  # C is class 0, A is class 2


def test_tcp_saturates_bottleneck_and_both_variants_run():
    for variant in ("reno", "cubic"):
        cfg = tcp_lab_config(duration_s=25)
        cfg["flows"][0]["tcp_variant"] = variant
        res = run(cfg)
        f = res["summary"]["flows"]["tcp1"]
        assert f["goodput_mbps"] > 7.5
        assert f["fast_retransmits"] >= 1
        assert all("cwnd" in s["flows"]["tcp1"] for s in res["samples"])
        assert max(s["flows"]["tcp1"]["cwnd"] for s in res["samples"]) > 20


def test_tcp_flows_share_bottleneck_fairly():
    res = run(tcp_lab_config(flows=2, duration_s=40))
    assert res["summary"]["totals"]["jain"] > 0.8
    assert res["summary"]["totals"]["goodput_mbps"] > 8.0


def test_tcp_conservation_with_acks():
    sim = Simulator(tcp_lab_config(duration_s=10))
    sim.run_until(10)
    c = sim.conservation()
    assert c["created"] == c["delivered"] + c["dropped"] + c["in_flight"]


def test_link_failure_drops_packets_and_reroutes():
    cfg = {"duration_s": 10,
           "nodes": [{"id": "A", "type": "host"}, {"id": "R1", "type": "router"}, {"id": "R2", "type": "router"},
                     {"id": "B", "type": "host"}],
           "links": [{"id": "LA", "a": "A", "b": "R1", "bandwidth_mbps": 100, "delay_ms": 1},
                     {"id": "P1", "a": "R1", "b": "B", "bandwidth_mbps": 10, "delay_ms": 1},
                     {"id": "P2", "a": "R1", "b": "R2", "bandwidth_mbps": 10, "delay_ms": 1},
                     {"id": "P3", "a": "R2", "b": "B", "bandwidth_mbps": 10, "delay_ms": 1}],
           "flows": [{"id": "f", "src": "A", "dst": "B", "kind": "cbr", "rate_mbps": 5}],
           "events": [{"type": "link_failure", "time": 4, "link": "P1", "duration": 3}]}
    res = run(cfg)
    assert any(m["type"] == "link_failure" for m in res["markers"])
    assert res["summary"]["links"]["R1>R2"]["arrivals"] > 0  # traffic was rerouted via R2
    assert res["summary"]["links"]["R1>B"]["drop_reasons"].get("link_down", 0) >= 0
    c = res["summary"]["totals"]["packets"]
    assert c["created"] == c["delivered"] + c["dropped"] + c["in_flight"]
    assert res["summary"]["flows"]["f"]["loss_pct"] < 5


def test_burst_event_adds_flow_and_marker():
    cfg = get_preset("three-sender")
    cfg["events"] = [{"type": "burst", "time": 5, "duration": 3, "rate_mbps": 20, "src": "A", "dst": "S"}]
    res = run(cfg)
    assert "burst1" in res["summary"]["flows"]
    assert [m["type"] for m in res["markers"]] == ["burst", "burst_end"]
    assert any("flash" in e["msg"].lower() or "ddos" in e["msg"].lower() for e in res["events"])


def test_event_log_is_plain_english(baseline):
    msgs = [e["msg"] for e in baseline["events"]]
    assert any(m.startswith("Packet dropped: buffer full on Router1 → Receiver link") for m in msgs)


def test_advisor_diagnoses_and_fix_improves():
    out = run_advisor(get_preset("three-sender"), "add_capacity")
    assert out["advice"]["congested"]
    assert out["advice"]["suggestions"][0]["id"] == "add_capacity"
    assert out["applied"]["improved"]
    assert out["applied"]["after"]["loss_pct"] < 1 < out["applied"]["before"]["loss_pct"]


def test_advisor_quiet_when_not_congested():
    cfg = get_preset("three-sender")
    cfg["links"][3]["bandwidth_mbps"] = 50
    res = run(cfg)
    assert advise(res["config"], res)["congested"] is False


def test_presets_all_run_and_validate():
    for p in list_presets():
        res = Simulator(p["config"]).run_with_frames(0.5)[0]
        assert res["summary"]["totals"]["sent_pkts"] > 0


def test_config_validation_errors():
    with pytest.raises(ConfigError):
        normalize_config({"nodes": [{"id": "A"}], "links": [{"id": "L", "a": "A", "b": "Z"}]})
    with pytest.raises(ConfigError):
        normalize_config({"nodes": [{"id": "A", "type": "router"}, {"id": "B"}],
                          "flows": [{"id": "f", "src": "A", "dst": "B"}]})


def test_apply_patch_does_not_mutate_original():
    cfg = normalize_config(get_preset("three-sender"))
    new = apply_patch(cfg, {"op": "set_bandwidth", "link": "LBN", "value": 99})
    assert cfg["links"][3]["bandwidth_mbps"] == 10 and new["links"][3]["bandwidth_mbps"] == 99
