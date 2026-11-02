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
