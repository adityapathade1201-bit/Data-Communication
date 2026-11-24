"""API tests (FastAPI TestClient). Requires: pip install -r requirements.txt"""
import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app
from app.sim.presets import get_preset


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    return TestClient(app)


def short_cfg():
    cfg = get_preset("three-sender")
    cfg["duration_s"] = 3
    return cfg


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_presets(client):
    data = client.get("/api/presets").json()
    assert {p["id"] for p in data} == {"three-sender", "office", "campus", "leaf-spine"}
    assert all(p["config"]["nodes"] for p in data)


def test_simulate_and_export(client):
    r = client.post("/api/simulate", json={"config": short_cfg()})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["totals"]["loss_pct"] > 20
    assert body["frames"] and body["samples"]
    csv = client.get(f"/api/export/{body['run_id']}?format=csv")
    assert csv.status_code == 200 and csv.text.startswith("t,scope,id")
    js = client.get(f"/api/export/{body['run_id']}?format=json")
    assert js.json()["run_id"] == body["run_id"]
    assert client.get("/api/export/nope?format=csv").status_code == 404


def test_simulate_by_preset_and_validation_error(client):
    assert client.post("/api/simulate", json={"preset": "three-sender", "include_frames": False}).status_code == 200
    bad = short_cfg()
    bad["flows"][0]["dst"] = "ghost"
    assert client.post("/api/simulate", json={"config": bad}).status_code == 422
    assert client.post("/api/simulate", json={"preset": "nope"}).status_code == 404


def test_experiments_run(client):
    r = client.post("/api/experiments/run", json={"config": short_cfg()})
    assert r.status_code == 200
    body = r.json()
    assert [e["id"] for e in body["experiments"]] == ["A", "B", "C-RED", "C-PRIO"]
    assert body["best"] == "B"
    assert any(row["metric"] == "loss_pct" for row in body["comparison"])


def test_advisor_and_apply(client):
    r = client.post("/api/advisor", json={"config": short_cfg()})
    assert r.status_code == 200 and r.json()["advice"]["congested"]
    r = client.post("/api/advisor", json={"config": short_cfg(), "apply": "add_capacity"})
    assert r.json()["applied"]["improved"] is True
    assert client.post("/api/advisor", json={"config": short_cfg(), "apply": "bogus"}).status_code == 404


def test_tcp_lab(client):
    r = client.post("/api/tcp-lab", json={"duration_s": 5})
    assert r.status_code == 200 and set(r.json()["runs"]) == {"reno", "cubic"}


def test_scenarios_roundtrip(client):
    saved = client.post("/api/scenarios", json={"name": "mine", "config": short_cfg()}).json()
    assert [s["id"] for s in client.get("/api/scenarios").json()] == [saved["id"]]
    assert client.get(f"/api/scenarios/{saved['id']}").json()["config"]["name"] == "3-sender bottleneck"
    assert client.delete(f"/api/scenarios/{saved['id']}").status_code == 200
    assert client.get("/api/scenarios").json() == []


def test_websocket_streams_snapshots_and_finishes(client):
    with client.websocket_connect("/ws/simulate") as ws:
        ws.send_json({"action": "start", "config": short_cfg(), "speed": 50})
        types, snap = [], None
        while True:
            msg = ws.receive_json()
            types.append(msg["type"])
            if msg["type"] == "snapshot" and snap is None:
                snap = msg
            if msg["type"] in ("done", "error"):
                break
        assert types[0] == "started" and types[-1] == "done"
        assert snap is not None and "queues" in snap and "packets" in snap
        assert msg["summary"]["totals"]["packets"]["created"] > 0


def test_websocket_rejects_invalid_config(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "start", "config": {"nodes": [{"id": "A"}], "flows": [{"id": "f", "src": "A", "dst": "Z"}]}})
        assert ws.receive_json()["type"] == "error"


def test_seven_sender_topology_is_accepted_and_simulated(client):
    cfg = get_preset("three-sender")
    base_link = next(link for link in cfg["links"] if link["a"] == "A" and link["b"] == "R1")
    template_flow = cfg["flows"][-1]
    for index in range(4, 8):
        host_id = f"NP_SENDER_{index}"
        cfg["nodes"].append({
            "id": host_id, "type": "host", "label": f"Sender {index}",
            "x": 170 + (index - 4) * 80, "y": 50 + (index - 4) * 90,
        })
        cfg["links"].append({**base_link, "id": f"NP_L{index}", "a": host_id, "b": "R1"})
        cfg["flows"].append({
            **template_flow, "id": f"f{index}", "src": host_id,
            "label": f"Sender {index} (4 Mbps)",
        })

    response = client.post("/api/simulate", json={"config": cfg, "include_frames": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["summary"]["flows"]) == 7
    assert {flow["src"] for flow in body["config"]["flows"]} == {
        "A", "B", "C", "NP_SENDER_4", "NP_SENDER_5", "NP_SENDER_6", "NP_SENDER_7"
    }


def test_vercel_storage_uses_writable_tmp(monkeypatch, tmp_path):
    monkeypatch.delenv("NETPULSE_DATA", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("NETPULSE_DATA", "/read-only/deployed/path")
    assert storage._default_data_dir() == tmp_path / "netpulse-data"


def test_websocket_reports_storage_failure_instead_of_dropping_connection(client, monkeypatch):
    def fail_save(_result):
        raise OSError("read-only file system")

    monkeypatch.setattr(storage, "save_run", fail_save)
    cfg = short_cfg()
    cfg["duration_s"] = 0.5
    with client.websocket_connect("/ws/simulate") as ws:
        ws.send_json({"action": "start", "config": cfg, "speed": 50})
        messages = []
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] == "error":
                break
        assert messages[0]["type"] == "started"
        assert messages[-1]["message"] == "Backend simulation failed: OSError: read-only file system"
