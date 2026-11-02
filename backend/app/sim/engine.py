"""NetPulse discrete-event network simulator (pure standard library).

Model: hosts + routers joined by full-duplex links. Every direction of a link is a
`Port` with its own output queue, serialization delay (size*8/bandwidth), propagation
delay and optional random loss. Traffic is CBR / Poisson / on-off bursty / TCP
(Reno or CUBIC). Everything is driven by a heapq event queue and a seeded RNG, so a
given (config, seed) pair always produces identical results.
"""
from __future__ import annotations

import heapq
import random
import zlib
from array import array
from collections import defaultdict
from itertools import chain

from .analysis import find_bottleneck
from .config import normalize_config, normalize_flow
from .queues import Packet, make_queue

ACK_SIZE = 40  # bytes


def percentile(sorted_vals, p):
    n = len(sorted_vals)
    if n == 0:
        return None
    k = (n - 1) * p
    f = int(k)
    c = min(f + 1, n - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def jain(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return 1.0
    s2 = sum(v * v for v in vals)
    if s2 <= 0:
        return 1.0
    return (sum(vals) ** 2) / (len(vals) * s2)


def _r(x, n=4):
    return None if x is None else round(x, n)


# --------------------------------------------------------------------------- Port
class Port:
    """One direction of a link: output queue + transmitter + propagation pipe."""

    def __init__(self, sim, link, a, b):
        self.sim = sim
        self.link = link
        self.link_id = link["id"]
        self.src, self.dst = a, b
        self.id = f"{a}>{b}"
        self.bw_mbps = link["bandwidth_mbps"]
        self.bw = self.bw_mbps * 1e6
        self.delay = link["delay_ms"] / 1000.0
        self.loss = link["loss_prob"]
        self.buffer = link["buffer_pkts"]
        self.policy = link["queue_policy"]
        self.queue = make_queue(link, 1000 * 8 / self.bw)
        self.up = True
        self.epoch = 0
        self.busy = False
        self.tx_pkt = None
        self.tx_start = 0.0
        self.prop = {}  # pkt id -> (pkt, depart, arrive)
        self.busy_total = 0.0
        self.last_busy = 0.0
        self.q_area = 0.0
        self.q_last_t = 0.0
        self.q_max = 0
        self.arrivals = self.drops = self.tx_pkts = 0
        self.arr_bytes = self.tx_bytes = 0
        self.i_arr = self.i_drops = 0
        self.snap_drops = 0
        self.drop_reasons = defaultdict(int)
        self.q_area_total = 0.0

    # --- queue-length bookkeeping
    def _qtick(self, now):
        a = len(self.queue) * (now - self.q_last_t)
        self.q_area += a
        self.q_area_total += a
        self.q_last_t = now

    def busy_at(self, t):
        return self.busy_total + ((t - self.tx_start) if self.busy else 0.0)

    # --- data path
    def send(self, pkt):
        sim = self.sim
        now = sim.now
        self.arrivals += 1
        self.i_arr += 1
        self.arr_bytes += pkt.size
        if not self.up:
            sim.drop(pkt, self, "link_down")
            return
        self._qtick(now)
        for victim, reason in self.queue.enqueue(pkt, now, sim.rng):
            sim.drop(victim, self, reason)
        if len(self.queue) > self.q_max:
            self.q_max = len(self.queue)
        if not self.busy:
            self._start_tx()

    def _start_tx(self):
        now = self.sim.now
        self._qtick(now)
        pkt = self.queue.dequeue(now)
        if pkt is None:
            return
        self.busy = True
        self.tx_pkt = pkt
        self.tx_start = now
        self.sim.schedule(now + pkt.size * 8 / self.bw, self._tx_done, pkt, self.epoch)

    def _tx_done(self, pkt, epoch):
        if epoch != self.epoch:
            return
        sim = self.sim
        now = sim.now
        self.busy = False
        self.tx_pkt = None
        self.busy_total += now - self.tx_start
        self.tx_pkts += 1
        self.tx_bytes += pkt.size
        if self.loss > 0 and sim.rng.random() < self.loss:
            sim.drop(pkt, self, "random_loss")
        else:
            arrive = now + self.delay
            self.prop[pkt.id] = (pkt, now, arrive)
            sim.schedule(arrive, self._arrive, pkt, self.epoch)
        if len(self.queue) > 0:
            self._start_tx()

    def _arrive(self, pkt, epoch):
        if epoch != self.epoch or pkt.id not in self.prop:
            return
        del self.prop[pkt.id]
        self.sim.node_receive(self.dst, pkt)

    # --- failures
    def fail(self):
        sim = self.sim
        now = sim.now
        self._qtick(now)
        self.up = False
        self.epoch += 1
        if self.busy:
            self.busy_total += now - self.tx_start
            self.busy = False
            pkt, self.tx_pkt = self.tx_pkt, None
            sim.drop(pkt, self, "link_down")
        for pkt in self.queue.clear():
            sim.drop(pkt, self, "link_down")
        pending = [v[0] for v in self.prop.values()]
        self.prop.clear()
        for pkt in pending:
            sim.drop(pkt, self, "link_down")

    def restore(self):
        self.up = True

    def in_flight(self):
        return len(self.queue) + (1 if self.busy else 0) + len(self.prop)


# --------------------------------------------------------------------------- Flows
class Flow:
    def __init__(self, sim, f):
        self.sim = sim
        self.cfg = f
        self.id = f["id"]
        self.src, self.dst, self.kind = f["src"], f["dst"], f["kind"]
        self.size = int(f["packet_size"])
        self.prio = int(f["priority"])
        self.t_start = float(f["start_s"])
        self.t_stop = f["stop_s"]
        self.rate = float(f["rate_mbps"])
        self.created = self.delivered = self.dropped = 0  # all packet kinds
        self.d_sent = self.d_deliv = self.d_drop = 0  # data packets only
        self.sent_bytes = self.deliv_bytes = self.uniq_bytes = 0
        self.delays = array("d")
        self.last_delay = None
        self.jit_sum = 0.0
        self.jit_n = 0
        self.i_sent_n = self.i_sent_b = self.i_deliv_b = self.i_uniq_b = self.i_drop = 0
        self.i_delays = []
        self.i_jit = 0.0
        self.i_jn = 0
        self.retx = 0

    # --- accounting
    def new_data(self, seq=0):
        pkt = self.sim.new_packet(self, "data", seq, self.size, self.src, self.dst)
        self.d_sent += 1
        self.sent_bytes += self.size
        self.i_sent_n += 1
        self.i_sent_b += self.size
        return pkt

    def on_drop(self, pkt):
        self.dropped += 1
        if pkt.kind == "data":
            self.d_drop += 1
            self.i_drop += 1

    def on_deliver(self, pkt):
        self.delivered += 1
        if pkt.kind == "data":
            self.on_data(pkt)
        else:
            self.on_ack(pkt)

    def on_data(self, pkt):
        self.record(pkt, True)

    def on_ack(self, pkt):
        pass

    def record(self, pkt, uniq):
        d = self.sim.now - pkt.created
        self.d_deliv += 1
        self.deliv_bytes += pkt.size
        self.i_deliv_b += pkt.size
        if uniq:
            self.uniq_bytes += pkt.size
            self.i_uniq_b += pkt.size
        self.delays.append(d)
        self.i_delays.append(d)
        if self.last_delay is not None:
            j = abs(d - self.last_delay)
            self.jit_sum += j
            self.jit_n += 1
            self.i_jit += j
            self.i_jn += 1
        self.last_delay = d

    def active_time(self, now):
        end = now if self.t_stop is None else min(now, self.t_stop)
        return max(end - self.t_start, 1e-9)

    # --- sampling
    def sample(self, dt):
        n = len(self.i_delays)
        sd = sorted(self.i_delays)
        d = {
            "throughput_mbps": self.i_deliv_b * 8 / dt / 1e6,
            "goodput_mbps": self.i_uniq_b * 8 / dt / 1e6,
            "sent_mbps": self.i_sent_b * 8 / dt / 1e6,
            "delay_avg_ms": 1000 * sum(sd) / n if n else None,
            "delay_p95_ms": 1000 * percentile(sd, 0.95) if n else None,
            "jitter_ms": 1000 * self.i_jit / self.i_jn if self.i_jn else None,
            "loss_pct": min(100.0, 100.0 * self.i_drop / self.i_sent_n) if self.i_sent_n else 0.0,
        }
        d.update(self.extra_sample())
        self.i_sent_n = self.i_sent_b = self.i_deliv_b = self.i_uniq_b = self.i_drop = 0
        self.i_delays = []
        self.i_jit = 0.0
        self.i_jn = 0
        return {k: _r(v) for k, v in d.items()}

    def extra_sample(self):
        return {}


class RateFlow(Flow):
    """CBR, Poisson or on/off bursty source (rate_mbps is the long-run average)."""

    def __init__(self, sim, f):
        super().__init__(sim, f)
        self.mean_gap = self.size * 8 / (self.rate * 1e6)
        b = float(f["burstiness"])
        self.bursty = self.kind == "bursty" and b > 1.0001
        if self.bursty:
            self.peak_gap = self.mean_gap / b
            self.on_mean = f["burst_on_ms"] / 1000.0
            self.off_mean = self.on_mean * (b - 1.0)
            self.phase_end = 0.0

    def begin(self):
        rng = self.sim.rng
        t0 = max(self.t_start, self.sim.now)
        if self.kind == "poisson":
            t0 += rng.expovariate(1 / self.mean_gap)
        else:
            t0 += rng.random() * self.mean_gap  # random phase: avoids lock-step arrivals
        if self.bursty:
            self.phase_end = t0 + rng.expovariate(1 / self.on_mean)
        self.sim.schedule(t0, self._emit)

    def _emit(self):
        sim = self.sim
        now = sim.now
        if self.t_stop is not None and now >= self.t_stop:
            return
        if self.bursty and now >= self.phase_end:
            sim.schedule(now + sim.rng.expovariate(1 / self.off_mean), self._wake)
            return
        sim.forward(self.src, self.new_data())
        if self.kind == "poisson":
            gap = sim.rng.expovariate(1 / self.mean_gap)
        elif self.bursty:
            gap = self.peak_gap
        else:
            gap = self.mean_gap
        sim.schedule(now + gap, self._emit)

    def _wake(self):
        self.phase_end = self.sim.now + self.sim.rng.expovariate(1 / self.on_mean)
        self._emit()


class TcpFlow(Flow):
    """Greedy bulk TCP: ACK-clocked, RTT estimation + RTO (RFC 6298 style, Karn's rule).

    Reno: slow start, congestion avoidance, fast retransmit / fast recovery and timeout.
    CUBIC: W(t)=C(t-K)^3+Wmax, beta=0.7, C=0.4, with a TCP-friendly region.
    Loss recovery uses SACK blocks (RFC 2018 / 6675-lite) by default; with sack=False it falls back to
    NewReno partial-ACK recovery. Dup-ACKs caused by go-back-N after a timeout are ignored (RFC 6582).
    """

    C = 0.4
    BETA = 0.7
    MIN_RTO = 0.2
    MAX_RTO = 8.0

    def __init__(self, sim, f):
        super().__init__(sim, f)
        self.variant = f["tcp_variant"]
        self.sack = bool(f.get("sack", True))
        self.rwnd = int(f["rwnd"])
        self.cwnd = 2.0
        self.ssthresh = float(self.rwnd)
        self.snd_una = self.snd_nxt = self.high_tx = 0
        self.dup = 0
        self.in_recovery = False
        self.partial_seen = False
        self.recover = 0
        self.sent_time = {}
        self.sb = []  # sender scoreboard: merged [start, end) ranges SACKed by the receiver
        self.sacked_cnt = 0
        self.retx_set = set()
        self.srtt = None
        self.rttvar = 0.0
        self.rto = 1.0
        self.min_rtt = None
        self.deadline = None
        self.timer_pending = False
        self.rcv_nxt = 0
        self.rcv_ranges = []  # receiver out-of-order ranges
        self.w_max = 0.0
        self.w_last_max = 0.0
        self.epoch = None
        self.K = 0.0
        self.origin = 0.0
        self.w_est = 0.0
        self.timeouts = 0
        self.fast_retx = 0
        self._last_log = -1e9

    # --- lifecycle
    def begin(self):
        self.sim.schedule(max(self.t_start, self.sim.now), self._try_send)

    def _sacked_below(self, limit):
        n = 0
        for s, e in self.sb:
            if s >= limit:
                break
            n += min(e, limit) - s
        return n

    def _is_sacked(self, seq):
        for s, e in self.sb:
            if s > seq:
                return False
            if seq < e:
                return True
        return False

    def _try_send(self):
        now = self.sim.now
        if self.t_stop is not None and now >= self.t_stop:
            return
        if self.in_recovery and self.sack:
            self._sack_send()
            return
        win = min(int(self.cwnd), self.rwnd)
        flight = self.snd_nxt - self.snd_una - (self._sacked_below(self.snd_nxt) if self.sb else 0)
        while True:
            while self.sb and self.snd_nxt < self.high_tx and self._is_sacked(self.snd_nxt):
                self.snd_nxt += 1  # receiver already has it
            if flight >= win:
                break
            self._send_seg(self.snd_nxt)
            self.snd_nxt += 1
            flight += 1

    def _bound(self):
        """Sequence of the 3rd-highest SACKed segment (everything unSACKed below it is deemed lost)."""
        need = 3
        for s, e in reversed(self.sb):
            n = e - s
            if n >= need:
                return e - need
            need -= n
        return None

    def _lost_list(self):
        bound = self._bound()
        if bound is None:
            return []
        out, pos = [], self.snd_una
        for s, e in self.sb:
            hi = min(s, bound)
            if pos < hi:
                out.extend(range(pos, hi))
            pos = max(pos, e)
            if pos >= bound:
                break
        if pos < bound:
            out.extend(range(pos, bound))
        return out

    def _sack_send(self):
        lost = self._lost_list()
        pipe = (self.snd_nxt - self.snd_una) - self.sacked_cnt - len(lost)
        pipe += sum(1 for s in lost if s in self.retx_set)
        budget = int(self.cwnd) - pipe
        for s in lost:
            if budget <= 0:
                return
            if s not in self.retx_set:
                self.retx_set.add(s)
                self._send_seg(s)
                budget -= 1
        while budget > 0 and self.snd_nxt - self.snd_una < self.rwnd:
            self._send_seg(self.snd_nxt)
            self.snd_nxt += 1
            budget -= 1

    def _send_seg(self, seq):
        retx = seq < self.high_tx
        pkt = self.new_data(seq)
        if retx:
            self.retx += 1
            self.sent_time.pop(seq, None)  # Karn: never time a retransmission
        else:
            self.high_tx = seq + 1
            self.sent_time[seq] = self.sim.now
        if self.deadline is None:
            self._restart_timer()
        self.sim.forward(self.src, pkt)

    # --- timer (lazy: one pending event, deadline moves)
    def _restart_timer(self):
        self.deadline = self.sim.now + self.rto
        if not self.timer_pending:
            self.timer_pending = True
            self.sim.schedule(self.deadline, self._timer_fire)

    def _timer_fire(self):
        self.timer_pending = False
        if self.deadline is None:
            return
        if self.sim.now + 1e-12 < self.deadline:
            self.timer_pending = True
            self.sim.schedule(self.deadline, self._timer_fire)
            return
        self.deadline = None
        self._timeout()

    # --- receiver side
    def on_data(self, pkt):
        seq = pkt.seq
        r = self.rcv_ranges
        new = False
        if seq == self.rcv_nxt:
            new = True
            self.rcv_nxt += 1
            if r and r[0][0] == self.rcv_nxt:
                self.rcv_nxt = r.pop(0)[1]
        elif seq > self.rcv_nxt:
            i = 0
            while i < len(r) and r[i][1] < seq:
                i += 1
            if i < len(r) and r[i][0] <= seq < r[i][1]:
                pass  # duplicate
            else:
                new = True
                if i < len(r) and r[i][1] == seq:
                    r[i][1] = seq + 1
                    if i + 1 < len(r) and r[i + 1][0] == r[i][1]:
                        r[i][1] = r[i + 1][1]
                        del r[i + 1]
                elif i < len(r) and r[i][0] == seq + 1:
                    r[i][0] = seq
                else:
                    r.insert(i, [seq, seq + 1])
        self.record(pkt, new)
        ack = self.sim.new_packet(self, "ack", self.rcv_nxt, ACK_SIZE, self.dst, self.src)
        if r and self.sack:
            first = next((b for b in r if b[0] <= seq < b[1]), None)
            blocks = [tuple(first)] if first else []
            for b in reversed(r):
                if len(blocks) >= 3:
                    break
                if first is None or b is not first:
                    blocks.append(tuple(b))
            ack.sack = tuple(blocks)
        self.sim.forward(self.dst, ack)

    # --- sender side
    def _merge_sack(self, blocks):
        rs = [list(b) for b in self.sb]
        rs.extend([max(s, self.snd_una), e] for s, e in blocks if e > self.snd_una)
        rs.sort()
        merged = []
        for s, e in rs:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        self.sb = merged
        self.sacked_cnt = sum(e - s for s, e in merged)

    def _trim_sb(self):
        if not self.sb:
            return
        sb = []
        for s, e in self.sb:
            if e > self.snd_una:
                sb.append([max(s, self.snd_una), e])
        self.sb = sb
        self.sacked_cnt = sum(e - s for s, e in sb)

    def on_ack(self, pkt):
        now = self.sim.now
        ack = pkt.seq
        partial = False
        if pkt.sack and self.sack:
            self._merge_sack(pkt.sack)
        if ack > self.snd_una:
            acked = ack - self.snd_una
            st = self.sent_time.get(ack - 1)
            if st is not None:
                self._rtt_sample(now - st)
            for s in range(self.snd_una, ack):
                self.sent_time.pop(s, None)
            self.snd_una = ack
            if self.snd_nxt < self.snd_una:
                self.snd_nxt = self.snd_una
            self._trim_sb()
            self.dup = 0
            if self.in_recovery:
                if ack >= self.recover:
                    self.in_recovery = False
                    self.retx_set.clear()
                    self.cwnd = max(self.ssthresh, 1.0)
                elif not self.sack:  # NewReno partial ACK: retransmit the next hole, stay in recovery
                    self._send_seg(self.snd_una)
                    self.cwnd = max(self.cwnd - acked + 1, 1.0)
                    partial = True
            else:
                self._grow(acked)
            if self.snd_nxt > self.snd_una:
                # "Impatient" NewReno (RFC 6582): only the first partial ACK re-arms the timer
                if not (partial and self.partial_seen):
                    self._restart_timer()
                if partial:
                    self.partial_seen = True
            else:
                self.deadline = None
        elif ack == self.snd_una and self.snd_nxt > self.snd_una:
            self.dup += 1
            if self.in_recovery:
                if not self.sack:
                    self.cwnd += 1
            elif not self.sack and self.dup == 3 and self.snd_una >= self.recover:
                self._fast_retransmit()
        if self.sack and not self.in_recovery and self.sacked_cnt >= 3 and self.snd_una >= self.recover:
            self._fast_retransmit()
        self._try_send()

    def _rtt_sample(self, r):
        if self.srtt is None:
            self.srtt = r
            self.rttvar = r / 2
        else:
            self.rttvar = 0.75 * self.rttvar + 0.25 * abs(self.srtt - r)
            self.srtt = 0.875 * self.srtt + 0.125 * r
        self.rto = min(max(self.srtt + 4 * self.rttvar, self.MIN_RTO), self.MAX_RTO)
        self.min_rtt = r if self.min_rtt is None else min(self.min_rtt, r)

    def _grow(self, acked):
        if self.cwnd < self.ssthresh:
            self.cwnd += acked  # slow start
        elif self.variant == "cubic":
            self._cubic_update(acked)
        else:
            self.cwnd += acked / self.cwnd  # Reno congestion avoidance
        self.cwnd = min(self.cwnd, float(self.rwnd))

    def _cubic_update(self, acked):
        now = self.sim.now
        if self.epoch is None:
            self.epoch = now
            if self.cwnd < self.w_max:
                self.K = ((self.w_max - self.cwnd) / self.C) ** (1.0 / 3.0)
                self.origin = self.w_max
            else:
                self.K = 0.0
                self.origin = self.cwnd
            self.w_est = self.cwnd
        t = now - self.epoch + (self.min_rtt or 0.0)
        target = self.origin + self.C * (t - self.K) ** 3
        if target > self.cwnd:
            self.cwnd += min((target - self.cwnd) / self.cwnd, 0.5) * acked
        else:
            self.cwnd += 0.01 * acked / self.cwnd
        self.w_est += 3 * (1 - self.BETA) / (1 + self.BETA) * acked / max(self.cwnd, 1.0)
        if self.w_est > self.cwnd:
            self.cwnd = self.w_est

    def _loss_reduce(self):
        flight = max(self.snd_nxt - self.snd_una - (self._sacked_below(self.snd_nxt) if self.sb else 0), 1)
        if self.variant == "cubic":
            before = self.cwnd
            self.w_max = before * (1 + self.BETA) / 2 if before < self.w_last_max else before
            self.w_last_max = before
            self.epoch = None
            self.ssthresh = max(before * self.BETA, 2.0)
        else:
            self.ssthresh = max(flight / 2.0, 2.0)

    def _fast_retransmit(self):
        before = self.cwnd
        self._loss_reduce()
        self.cwnd = self.ssthresh if self.sack else self.ssthresh + 3
        self.in_recovery = True
        self.partial_seen = False
        self.recover = self.snd_nxt
        self.retx_set.clear()
        self.fast_retx += 1
        if not self.sack:
            self._send_seg(self.snd_una)
        self._log(f"{self.variant.upper()} flow {self.cfg['label']}: lost packets were detected from duplicate ACKs/SACKs "
                  f"and retransmitted (fast retransmit); the congestion window shrank from {before:.0f} to "
                  f"{self.ssthresh:.0f} segments.")

    def _timeout(self):
        if self.snd_una >= self.snd_nxt:
            return
        if self.t_stop is not None and self.sim.now >= self.t_stop:
            return
        before = self.cwnd
        self._loss_reduce()
        self.cwnd = 1.0
        self.dup = 0
        self.in_recovery = False
        self.retx_set.clear()
        self.snd_nxt = self.snd_una  # go-back-N (segments the receiver SACKed are skipped)
        self.recover = self.high_tx
        self.rto = min(self.rto * 2, self.MAX_RTO)
        self.timeouts += 1
        self._restart_timer()
        self._log(f"{self.variant.upper()} flow {self.cfg['label']}: no ACK arrived before the timeout, so the window "
                  f"dropped from {before:.0f} to 1 segment and slow start restarted.", "error")
        self._try_send()

    def _log(self, msg, level="warn"):
        if self.sim.now - self._last_log >= 0.25:
            self._last_log = self.sim.now
            self.sim.log(level, "tcp", msg)

    def extra_sample(self):
        return {"cwnd": self.cwnd, "ssthresh": min(self.ssthresh, float(self.rwnd)),
                "srtt_ms": None if self.srtt is None else self.srtt * 1000}


# --------------------------------------------------------------------------- Simulator
class Simulator:
    def __init__(self, cfg):
        self.cfg = normalize_config(cfg)
        c = self.cfg
        self.duration = c["duration_s"]
        self.interval = c["sample_interval_s"]
        self.rng = random.Random(c["seed"])
        self.now = 0.0
        self._heap = []
        self._n = 0
        self.nodes = {n["id"]: n for n in c["nodes"]}
        self.ports = {}
        self.link_ports = {}
        self.out_ports = {n: [] for n in self.nodes}
        for l in c["links"]:
            pf, pr = Port(self, l, l["a"], l["b"]), Port(self, l, l["b"], l["a"])
            for p in (pf, pr):
                self.ports[p.id] = p
                self.out_ports[p.src].append(p)
            self.link_ports[l["id"]] = [pf, pr]
        self.flows = {}
        self.created = self.delivered = self.dropped = 0
        self._pid = 0
        self.events = []
        self.markers = []
        self.samples = []
        self._k = 0
        self.last_sample_t = 0.0
        self._drop_acc = defaultdict(int)
        self._flags = {}
        self._cursor = {"samples": 0, "events": 0, "markers": 0}
        self._burst_n = 0
        self._finished = False
        self.routes = {}
        self._recompute_routes()
        for f in c["flows"]:
            self._add_flow(f)
        for ev in c["events"]:
            self._schedule_event(ev)
        self._schedule_next_sample()

    # --- scheduling
    def schedule(self, t, fn, *args):
        heapq.heappush(self._heap, (t, self._n, fn, args))
        self._n += 1

    def run_until(self, t):
        t = min(t, self.duration)
        heap = self._heap
        while heap and heap[0][0] <= t:
            tm, _, fn, args = heapq.heappop(heap)
            self.now = tm
            fn(*args)
        self.now = max(self.now, t)

    def run(self):
        self.run_until(self.duration)
        return self.finish()

    # --- helpers
    def label(self, node):
        return self.nodes[node]["label"]

    def plabel(self, port):
        return f"{self.label(port.src)} → {self.label(port.dst)} link"

    def log(self, level, cat, msg):
        if len(self.events) < 3000:
            self.events.append({"t": round(self.now, 3), "level": level, "cat": cat, "msg": msg})

    def marker(self, kind, label):
        self.markers.append({"t": round(self.now, 3), "type": kind, "label": label})

    def new_packet(self, flow, kind, seq, size, src, dst):
        self._pid += 1
        self.created += 1
        flow.created += 1
        return Packet(self._pid, flow.id, src, dst, size, kind, seq, self.now, flow.prio)

    def _add_flow(self, f):
        cls = TcpFlow if f["kind"] == "tcp" else RateFlow
        fl = cls(self, f)
        self.flows[fl.id] = fl
        fl.begin()
        return fl

    # --- routing / forwarding
    def _recompute_routes(self):
        radj = defaultdict(list)
        for p in self.ports.values():
            if p.up:
                radj[p.dst].append(p)
        routes = {n: {} for n in self.nodes}
        for dst in self.nodes:
            dist = {dst: 0}
            frontier = [dst]
            while frontier:
                nxt = []
                for v in frontier:
                    if v != dst and self.nodes[v]["type"] == "host":
                        continue
                    for p in radj[v]:
                        if p.src not in dist:
                            dist[p.src] = dist[v] + 1
                            nxt.append(p.src)
                frontier = nxt
            for u, du in dist.items():
                if u == dst:
                    continue
                hops = [p for p in self.out_ports[u]
                        if p.up and dist.get(p.dst) == du - 1 and (p.dst == dst or self.nodes[p.dst]["type"] == "router")]
                if hops:
                    routes[u][dst] = hops
        self.routes = routes

    def forward(self, node, pkt):
        hops = self.routes[node].get(pkt.dst)
        if not hops:
            self.drop(pkt, None, "no_route")
            return
        port = hops[0] if len(hops) == 1 else hops[zlib.crc32((pkt.flow + node).encode()) % len(hops)]
        port.send(pkt)

    def node_receive(self, node, pkt):
        if pkt.dst == node:
            self.delivered += 1
            self.flows[pkt.flow].on_deliver(pkt)
        else:
            self.forward(node, pkt)

    def drop(self, pkt, port, reason):
        self.dropped += 1
        self.flows[pkt.flow].on_drop(pkt)
        if port is not None:
            port.drops += 1
            port.i_drops += 1
            port.snap_drops += 1
            port.drop_reasons[reason] += 1
            self._drop_acc[(port.id, reason)] += 1

    # --- what-if events
    def _schedule_event(self, ev):
        if ev["type"] == "link_failure":
            self.schedule(ev["time"], self._link_state, ev["link"], False)
            if ev["duration"] is not None:
                self.schedule(ev["time"] + ev["duration"], self._link_state, ev["link"], True)
        else:
            self.schedule(ev["time"], self._burst_start, ev)

    def _link_state(self, link_id, up):
        for p in self.link_ports[link_id]:
            p.restore() if up else p.fail()
        self._recompute_routes()
        a, b = self.link_ports[link_id][0].src, self.link_ports[link_id][0].dst
        name = f"{self.label(a)} ↔ {self.label(b)}"
        if up:
            self.marker("link_restore", f"Link restored: {name}")
            self.log("info", "event", f"Link {name} is back up; routing tables were recomputed.")
        else:
            self.marker("link_failure", f"Link failure: {name}")
            self.log("error", "event", f"Link {name} failed. Packets on it were lost and routes were recomputed "
                                       f"to use any alternate path.")

    def _burst_start(self, ev):
        self._burst_n += 1
        fid = f"burst{self._burst_n}"
        f = normalize_flow({"id": fid, "src": ev["src"], "dst": ev["dst"], "kind": ev["kind"], "rate_mbps": ev["rate_mbps"],
                            "packet_size": ev["packet_size"], "priority": ev["priority"], "start_s": self.now,
                            "stop_s": self.now + ev["duration"], "label": f"{ev['label']} #{self._burst_n}"})
        self._add_flow(f)
        self.marker("burst", f"{ev['label']}: +{ev['rate_mbps']:g} Mbps for {ev['duration']:g}s")
        self.log("error", "event", f"{ev['label']} began: an extra {ev['rate_mbps']:g} Mbps of traffic from "
                                   f"{self.label(ev['src'])} to {self.label(ev['dst'])} for {ev['duration']:g}s.")
        self.schedule(self.now + ev["duration"], self._burst_end, ev)

    def _burst_end(self, ev):
        self.marker("burst_end", f"{ev['label']} ended")
        self.log("info", "event", f"{ev['label']} ended; offered load returns to normal.")

    # --- sampling
    def _schedule_next_sample(self):
        self._k += 1
        t = self._k * self.interval
        if abs(t - self.duration) < 1e-9:
            t = self.duration
        if t <= self.duration + 1e-9:
            self.schedule(t, self._sample, False)

    def _sample(self, final=False):
        t = self.now
        dt = t - self.last_sample_t
        if dt <= 1e-12:
            return
        s = {"t": round(t, 6), "flows": {}, "links": {}, "global": {}}
        tp = gp = sent_n = drop_n = deliv_n = 0.0
        dsum = 0.0
        active_tp = []
        for fid, fl in self.flows.items():
            n_d = len(fl.i_delays)
            dsum += sum(fl.i_delays)
            sent_n += fl.i_sent_n
            drop_n += fl.i_drop
            deliv_n += n_d
            d = fl.sample(dt)
            s["flows"][fid] = d
            tp += d["throughput_mbps"]
            gp += d["goodput_mbps"]
            if fl.t_start < t and (fl.t_stop is None or fl.t_stop > t - dt):
                active_tp.append(d["throughput_mbps"])
        max_util = max_fill = 0.0
        for pid, p in self.ports.items():
            p._qtick(t)
            util = min(1.0, (p.busy_at(t) - p.last_busy) / dt)
            p.last_busy = p.busy_at(t)
            qavg = p.q_area / dt
            fill = qavg / p.buffer
            s["links"][pid] = {
                "link": p.link_id, "util": _r(util), "throughput_mbps": _r(util * p.bw_mbps),
                "qlen": len(p.queue), "qavg": _r(qavg), "qmax": p.q_max, "fill": _r(fill),
                "drops": p.i_drops, "loss_pct": _r(100.0 * p.i_drops / p.i_arr if p.i_arr else 0.0),
                "up": p.up}
            self._congestion_logs(p, util, fill)
            max_util, max_fill = max(max_util, util), max(max_fill, fill)
            p.q_area = 0.0
            p.q_max = len(p.queue)
            p.i_arr = p.i_drops = 0
        s["global"] = {
            "throughput_mbps": _r(tp), "goodput_mbps": _r(gp),
            "loss_pct": _r(100.0 * drop_n / sent_n if sent_n else 0.0),
            "delay_avg_ms": _r(1000 * dsum / deliv_n) if deliv_n else None,
            "jain": _r(jain(active_tp)), "max_util": _r(max_util), "max_fill": _r(max_fill)}
        self.samples.append(s)
        self._flush_drop_logs(dt)
        self.last_sample_t = t
        if not final:
            self._schedule_next_sample()

    def _congestion_logs(self, p, util, fill):
        key = p.id
        fl = self._flags.setdefault(key, {"sat": False, "q": False})
        if p.up and util >= 0.95 and not fl["sat"]:
            fl["sat"] = True
            self.log("warn", "congestion", f"{self.plabel(p)} is saturated ({util * 100:.0f}% busy): offered traffic "
                                           f"has reached its {p.bw_mbps:g} Mbps capacity, so it is the bottleneck.")
        elif fl["sat"] and util < 0.8:
            fl["sat"] = False
            self.log("info", "congestion", f"{self.plabel(p)} is no longer saturated ({util * 100:.0f}% busy).")
        if fill >= 0.5 and not fl["q"]:
            fl["q"] = True
            self.log("warn", "congestion", f"Queue on {self.plabel(p)} is more than half full ({len(p.queue)} of "
                                           f"{p.buffer} packets), so packets now wait longer and delay is rising.")
        elif fl["q"] and fill < 0.1:
            fl["q"] = False
            self.log("info", "congestion", f"Queue on {self.plabel(p)} has drained.")

    def _flush_drop_logs(self, dt):
        for (pid, reason), n in self._drop_acc.items():
            p = self.ports[pid]
            lab = self.plabel(p)
            if reason == "buffer_full":
                msg = f"Packet dropped: buffer full on {lab} ({n} packet{'s' if n != 1 else ''} in the last {dt:.2f}s; the buffer holds {p.buffer} packets)."
            elif reason == "red_early":
                msg = f"RED on {lab} dropped {n} packet{'s' if n != 1 else ''} early, warning senders before the buffer fills."
            elif reason == "red_forced":
                msg = f"RED on {lab} dropped {n} packet{'s' if n != 1 else ''} because the average queue passed its upper threshold."
            elif reason == "preempted":
                msg = f"Priority queue on {lab} discarded {n} lower-priority packet{'s' if n != 1 else ''} to make room for more important traffic."
            elif reason == "random_loss":
                msg = f"{n} packet{'s' if n != 1 else ''} lost on {lab} due to random link loss (e.g. noise)."
            else:
                msg = f"{n} packet{'s' if n != 1 else ''} lost on {lab} because the link is down."
            self.log("warn", "drop", msg)
        self._drop_acc.clear()

    # --- live view
    def snapshot(self, max_packets=250):
        pk = []
        for p in self.ports.values():
            for pkt, dep, arr in p.prop.values():
                frac = (self.now - dep) / (arr - dep) if arr > dep else 1.0
                pk.append([p.id, round(min(max(frac, 0.0), 1.0), 3), 0 if pkt.kind == "data" else 1, pkt.flow])
        if len(pk) > max_packets:
            step = len(pk) / max_packets
            pk = [pk[int(i * step)] for i in range(max_packets)]
        drops = {}
        for pid, p in self.ports.items():
            if p.snap_drops:
                drops[pid] = p.snap_drops
                p.snap_drops = 0
        last = self.samples[-1]["links"] if self.samples else {}
        return {"t": round(self.now, 4), "packets": pk,
                "queues": {pid: len(p.queue) for pid, p in self.ports.items()},
                "util": {pid: v["util"] for pid, v in last.items()},
                "up": {pid: p.up for pid, p in self.ports.items() if not p.up},
                "drops": drops}

    def new_since_last(self):
        out = {}
        for key, src in (("samples", self.samples), ("events", self.events), ("markers", self.markers)):
            out[key] = src[self._cursor[key]:]
            self._cursor[key] = len(src)
        return out

    def run_with_frames(self, frame_dt=0.1, max_packets=60):
        frames = []
        t = 0.0
        while t < self.duration - 1e-9:
            t = min(t + frame_dt, self.duration)
            self.run_until(t)
            frames.append(self.snapshot(max_packets))
        return self.finish(), frames

    # --- results
    def in_flight(self):
        return sum(p.in_flight() for p in self.ports.values())

    def conservation(self):
        return {"created": self.created, "delivered": self.delivered, "dropped": self.dropped,
                "in_flight": self.in_flight()}

    def finish(self):
        if self.now - self.last_sample_t > 1e-9:
            self._sample(final=True)
        self._finished = True
        return {"config": self.cfg, "summary": self.summary(), "samples": self.samples,
                "events": self.events, "markers": self.markers}

    def summary(self):
        now = max(self.now, 1e-9)
        flows = {}
        all_delays = []
        tps = []
        for fid, fl in self.flows.items():
            act = fl.active_time(now)
            sd = sorted(fl.delays)
            all_delays.append(fl.delays)
            tp = fl.deliv_bytes * 8 / act / 1e6
            tps.append(tp)
            d = {"label": fl.cfg["label"], "kind": fl.kind, "src": fl.src, "dst": fl.dst, "priority": fl.prio,
                 "sent_pkts": fl.d_sent, "delivered_pkts": fl.d_deliv, "dropped_pkts": fl.d_drop,
                 "loss_pct": _r(100.0 * fl.d_drop / fl.d_sent if fl.d_sent else 0.0),
                 "offered_mbps": _r(fl.sent_bytes * 8 / act / 1e6), "throughput_mbps": _r(tp),
                 "goodput_mbps": _r(fl.uniq_bytes * 8 / act / 1e6),
                 "delay_avg_ms": _r(1000 * sum(sd) / len(sd)) if sd else None,
                 "delay_p95_ms": _r(1000 * percentile(sd, 0.95)) if sd else None,
                 "jitter_ms": _r(1000 * fl.jit_sum / fl.jit_n) if fl.jit_n else None}
            if isinstance(fl, TcpFlow):
                d.update({"tcp_variant": fl.variant, "retransmits": fl.retx, "timeouts": fl.timeouts,
                          "fast_retransmits": fl.fast_retx, "cwnd": _r(fl.cwnd), "ssthresh": _r(min(fl.ssthresh, fl.rwnd))})
            flows[fid] = d
        ports = {}
        for pid, p in self.ports.items():
            p._qtick(now)
            qavg = p.q_area_total / now
            ports[pid] = {
                "link": p.link_id, "src": p.src, "dst": p.dst, "label": self.plabel(p), "bandwidth_mbps": p.bw_mbps,
                "buffer_pkts": p.buffer, "policy": p.policy, "util_avg": _r(p.busy_at(now) / now),
                "throughput_mbps": _r(p.busy_at(now) / now * p.bw_mbps), "offered_mbps": _r(p.arr_bytes * 8 / now / 1e6),
                "arrivals": p.arrivals, "drops": p.drops, "loss_pct": _r(100.0 * p.drops / p.arrivals if p.arrivals else 0.0),
                "qlen_avg": _r(qavg), "fill_avg": _r(qavg / p.buffer), "drop_reasons": dict(p.drop_reasons)}
        pooled = sorted(chain.from_iterable(all_delays))
        jn = sum(f.jit_n for f in self.flows.values())
        sent = sum(f.d_sent for f in self.flows.values())
        drp = sum(f.d_drop for f in self.flows.values())
        totals = {
            "throughput_mbps": _r(sum(tps)),
            "goodput_mbps": _r(sum(f.uniq_bytes * 8 / f.active_time(now) / 1e6 for f in self.flows.values())),
            "delay_avg_ms": _r(1000 * sum(pooled) / len(pooled)) if pooled else None,
            "delay_p95_ms": _r(1000 * percentile(pooled, 0.95)) if pooled else None,
            "jitter_ms": _r(1000 * sum(f.jit_sum for f in self.flows.values()) / jn) if jn else None,
            "loss_pct": _r(100.0 * drp / sent if sent else 0.0),
            "jain": _r(jain(tps)), "sent_pkts": sent, "dropped_pkts": drp,
            "packets": self.conservation()}
        s = {"duration_s": round(now, 4), "flows": flows, "links": ports, "totals": totals}
        s["bottleneck"] = find_bottleneck(s)
        return s
