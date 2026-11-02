"""Pydantic request/response models (validation for the REST + WebSocket API)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Policy = Literal["droptail", "red", "priority"]


class NodeModel(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    type: Literal["host", "router"] = "host"
    label: Optional[str] = None
    x: float = 0
    y: float = 0


class LinkModel(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    a: str
    b: str
    bandwidth_mbps: float = Field(10, gt=0, le=1_000_000)
    delay_ms: float = Field(5, ge=0, le=10_000)
    buffer_pkts: int = Field(100, ge=1, le=100_000)
    loss_prob: float = Field(0, ge=0, le=1)
    queue_policy: Policy = "droptail"
    red_min_th: Optional[float] = None
    red_max_th: Optional[float] = None
    red_max_p: float = Field(0.1, gt=0, le=1)
    red_wq: float = Field(0.02, gt=0, le=1)


class FlowModel(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    src: str
    dst: str
    kind: Literal["cbr", "poisson", "bursty", "tcp"] = "cbr"
    rate_mbps: float = Field(1.0, gt=0, le=1_000_000)
    packet_size: int = Field(1000, ge=64, le=9000)
    start_s: float = Field(0, ge=0)
    stop_s: Optional[float] = None
    priority: int = Field(0, ge=0, le=2)
    burstiness: float = Field(4.0, ge=1, le=100)
    burst_on_ms: float = Field(100.0, ge=1, le=100_000)
    tcp_variant: Literal["reno", "cubic"] = "reno"
    rwnd: int = Field(256, ge=4, le=100_000)
    sack: bool = True
    label: Optional[str] = None


class EventModel(BaseModel):
    type: Literal["link_failure", "burst"]
    time: float = Field(5, ge=0)
    duration: Optional[float] = None
    link: Optional[str] = None
    rate_mbps: Optional[float] = None
    src: Optional[str] = None
    dst: Optional[str] = None
    kind: Optional[str] = None
    priority: Optional[int] = None
    packet_size: Optional[int] = None
    label: Optional[str] = None


class SimConfig(BaseModel):
    name: str = "scenario"
    duration_s: float = Field(20, ge=0.5, le=600)
    seed: int = 1
    sample_interval_s: float = Field(0.25, ge=0.01, le=10)
    bottleneck_link: Optional[str] = None
    nodes: list[NodeModel]
    links: list[LinkModel] = []
    flows: list[FlowModel] = []
    events: list[EventModel] = []

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class SimulateRequest(BaseModel):
    config: Optional[SimConfig] = None
    preset: Optional[str] = None
    include_frames: bool = True
    frame_dt: float = Field(0.1, ge=0.02, le=2)


class ExperimentRequest(BaseModel):
    config: Optional[SimConfig] = None
    preset: Optional[str] = "three-sender"
    raised_bandwidth_mbps: Optional[float] = Field(None, gt=0)
    bottleneck_link: Optional[str] = None
    policies: list[Literal["droptail", "red", "priority"]] = ["red", "priority"]


class AdvisorRequest(BaseModel):
    config: Optional[SimConfig] = None
    preset: Optional[str] = None
    apply: Optional[str] = None


class TcpLabRequest(BaseModel):
    bandwidth_mbps: float = Field(10, gt=0, le=1000)
    delay_ms: float = Field(20, ge=0, le=1000)
    buffer_pkts: int = Field(50, ge=1, le=10000)
    flows: int = Field(1, ge=1, le=4)
    duration_s: float = Field(30, ge=5, le=120)
    seed: int = 1
    queue_policy: Policy = "droptail"


class ScenarioSave(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    config: SimConfig
