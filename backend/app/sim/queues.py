"""Packets and output-queue disciplines (DropTail, RED, strict Priority)."""
from __future__ import annotations

from collections import deque


class Packet:
    __slots__ = ("id", "flow", "src", "dst", "size", "kind", "seq", "created", "prio", "sack")

    def __init__(self, pid, flow, src, dst, size, kind, seq, created, prio):
        self.id = pid
        self.flow = flow
        self.src = src
        self.dst = dst
        self.size = size
        self.kind = kind  # "data" | "ack"
        self.seq = seq
        self.created = created
        self.prio = prio
        self.sack = None


class DropTailQueue:
    """Plain FIFO; arrivals are discarded when the buffer is full."""

    policy = "droptail"

    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self.q: deque = deque()

    def __len__(self) -> int:
        return len(self.q)

    def enqueue(self, pkt, now, rng):
        """Returns a list of (packet, reason) that were dropped (may include pkt)."""
        if len(self.q) >= self.capacity:
            return [(pkt, "buffer_full")]
        self.q.append(pkt)
        return []

    def dequeue(self, now):
        return self.q.popleft() if self.q else None

    def clear(self):
        out = list(self.q)
        self.q.clear()
        return out

    def packets(self):
        return list(self.q)


class REDQueue(DropTailQueue):
    """Random Early Detection (Floyd & Jacobson) with an EWMA of queue length."""

    policy = "red"

    def __init__(self, capacity, min_th, max_th, max_p, wq, pkt_time):
        super().__init__(capacity)
        self.min_th = float(min_th)
        self.max_th = max(float(max_th), self.min_th + 1e-9)
        self.max_p = float(max_p)
        self.wq = float(wq)
        self.pkt_time = max(pkt_time, 1e-9)  # typical packet transmission time
        self.avg = 0.0
        self.count = -1
        self.idle_since = 0.0

    def enqueue(self, pkt, now, rng):
        qlen = len(self.q)
        if qlen > 0:
            self.avg = (1.0 - self.wq) * self.avg + self.wq * qlen
        else:
            m = max(0.0, (now - self.idle_since) / self.pkt_time)
            self.avg *= (1.0 - self.wq) ** m
        if qlen >= self.capacity:
            self.count = -1
            return [(pkt, "buffer_full")]
        if self.avg < self.min_th:
            self.count = -1
        elif self.avg >= self.max_th:
            self.count = 0
            return [(pkt, "red_forced")]
        else:
            self.count += 1
            pb = self.max_p * (self.avg - self.min_th) / (self.max_th - self.min_th)
            denom = 1.0 - self.count * pb
            pa = pb / denom if denom > 0 else 1.0
            if rng.random() < pa:
                self.count = 0
                return [(pkt, "red_early")]
        self.q.append(pkt)
        return []

    def dequeue(self, now):
        pkt = super().dequeue(now)
        if not self.q:
            self.idle_since = now
        return pkt


class PriorityQueue:
    """Strict priority, class 0 is served first. Shared buffer with push-out of lower classes."""

    policy = "priority"

    def __init__(self, capacity: int, classes: int = 3):
        self.capacity = max(1, int(capacity))
        self.qs = [deque() for _ in range(classes)]
        self.n = 0

    def __len__(self) -> int:
        return self.n

    def enqueue(self, pkt, now, rng):
        c = min(max(pkt.prio, 0), len(self.qs) - 1)
        if self.n >= self.capacity:
            for worst in range(len(self.qs) - 1, c, -1):
                if self.qs[worst]:
                    victim = self.qs[worst].pop()
                    self.qs[c].append(pkt)
                    return [(victim, "preempted")]
            return [(pkt, "buffer_full")]
        self.qs[c].append(pkt)
        self.n += 1
        return []

    def dequeue(self, now):
        for q in self.qs:
            if q:
                self.n -= 1
                return q.popleft()
        return None

    def clear(self):
        out = []
        for q in self.qs:
            out.extend(q)
            q.clear()
        self.n = 0
        return out

    def packets(self):
        return [p for q in self.qs for p in q]


def make_queue(link: dict, pkt_time: float):
    policy = link["queue_policy"]
    cap = link["buffer_pkts"]
    if policy == "red":
        return REDQueue(cap, link["red_min_th"], link["red_max_th"], link["red_max_p"], link["red_wq"], pkt_time)
    if policy == "priority":
        return PriorityQueue(cap)
    return DropTailQueue(cap)
