"""Background system monitor — the one place that does heavy sampling.

The whole point of this module: keep every slow operation (process iteration,
``exe()`` syscalls, ``Info.plist`` disk reads) OFF the UI thread. A single daemon
thread samples on a fixed cadence and publishes an immutable, display-ready
``Snapshot``. The menu bar UI only ever reads the latest snapshot and paints
strings — so the menu can never freeze, even when the machine is thrashing
(which is exactly when surgebar needs to stay responsive).

Design contract:
- One writer (the sampler thread), many readers (the UI timer). All shared state
  is guarded by a lock; snapshots are immutable once published.
- A single bad sample never kills the thread — every iteration is wrapped.
- A watchdog timestamp lets the UI show "sampling slow" instead of lying with a
  stale number when the sampler stalls.
- A per-pid label cache with a short TTL avoids re-running ``exe()`` and reading
  the same ``Info.plist`` every 5 seconds.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import psutil

from .process_naming import display_label
from .signals import CORE_COUNT

# ─── Thresholds (single source of truth for surge state) ─────────────────────

CPU_WARN_PERCENT = 60
CPU_CRIT_PERCENT = 85
LOAD_PER_CORE_WARN = 1.0
LOAD_PER_CORE_CRIT = 2.0

STATUS_GREEN = "🟢"
STATUS_YELLOW = "🟡"
STATUS_RED = "🔴"

_SPARK_TICKS = "▁▂▃▄▅▆▇█"
_LABEL_CACHE_TTL_SECONDS = 60.0


def status_dot(cpu_percent: float, load1: float) -> str:
    per_core = load1 / CORE_COUNT
    if cpu_percent >= CPU_CRIT_PERCENT or per_core >= LOAD_PER_CORE_CRIT:
        return STATUS_RED
    if cpu_percent >= CPU_WARN_PERCENT or per_core >= LOAD_PER_CORE_WARN:
        return STATUS_YELLOW
    return STATUS_GREEN


def is_surging(cpu_percent: float, load1: float) -> bool:
    return cpu_percent >= CPU_CRIT_PERCENT or (load1 / CORE_COUNT) >= LOAD_PER_CORE_CRIT


def sparkline(values: list[float], width: int = 8) -> str:
    """Render recent CPU% as a unicode sparkline scaled 0 to 100."""
    if not values:
        return ""
    recent = values[-width:]
    out = []
    for value in recent:
        clamped = max(0.0, min(100.0, value))
        idx = int(clamped / 100.0 * (len(_SPARK_TICKS) - 1))
        out.append(_SPARK_TICKS[idx])
    return "".join(out)


@dataclass(frozen=True)
class ProcRow:
    pid: int
    name: str
    cpu_percent: float
    label: str  # display-ready, computed off the UI thread


@dataclass(frozen=True)
class Snapshot:
    ts: float
    cpu_percent: float
    load1: float
    dot: str
    surging: bool
    rows: tuple[ProcRow, ...]


@dataclass
class SurgeEvent:
    ts: float
    summary: str


@dataclass
class Monitor:
    poll_interval: float
    process_slots: int
    _latest: Snapshot | None = field(default=None, init=False)
    _cpu_history: deque[float] = field(default_factory=lambda: deque(maxlen=30), init=False)
    _surge_history: deque[SurgeEvent] = field(default_factory=lambda: deque(maxlen=20), init=False)
    _paused: bool = field(default=False, init=False)
    _last_ok: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _label_cache: dict[int, tuple[float, str]] = field(default_factory=dict, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        psutil.cpu_percent(interval=None)  # prime the counter
        self._thread = threading.Thread(target=self._loop, name="surgebar-sampler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            if not self._paused:
                with contextlib.suppress(Exception):
                    self._sample_once()
            time.sleep(self.poll_interval)

    # ── sampling (runs on the sampler thread only) ───────────────────────────

    def _sample_once(self) -> None:
        cpu_percent = psutil.cpu_percent(interval=None)
        load1, _, _ = os.getloadavg()
        rows = self._top_rows()
        snapshot = Snapshot(
            ts=time.time(),
            cpu_percent=cpu_percent,
            load1=load1,
            dot=status_dot(cpu_percent, load1),
            surging=is_surging(cpu_percent, load1),
            rows=rows,
        )
        with self._lock:
            self._latest = snapshot
            self._cpu_history.append(cpu_percent)
            self._last_ok = snapshot.ts

    def _top_rows(self) -> tuple[ProcRow, ...]:
        procs: list[dict[str, Any]] = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                procs.append(p.info)
        procs.sort(key=lambda x: x.get("cpu_percent") or 0.0, reverse=True)
        rows: list[ProcRow] = []
        for info in procs[: self.process_slots]:
            pid = info["pid"]
            name = info.get("name") or "?"
            rows.append(
                ProcRow(
                    pid=pid,
                    name=name,
                    cpu_percent=round(info.get("cpu_percent") or 0.0, 1),
                    label=self._cached_label(pid, name),
                )
            )
        return tuple(rows)

    def _cached_label(self, pid: int, name: str) -> str:
        now = time.time()
        cached = self._label_cache.get(pid)
        if cached and (now - cached[0]) < _LABEL_CACHE_TTL_SECONDS:
            return cached[1]
        label = display_label(pid, name)  # may exe() + read Info.plist — sampler thread only
        self._label_cache[pid] = (now, label)
        if len(self._label_cache) > 256:
            self._prune_label_cache(now)
        return label

    def _prune_label_cache(self, now: float) -> None:
        stale = [pid for pid, (ts, _) in self._label_cache.items() if now - ts > _LABEL_CACHE_TTL_SECONDS]
        for pid in stale:
            del self._label_cache[pid]

    # ── reads (safe from any thread) ─────────────────────────────────────────

    @property
    def latest(self) -> Snapshot | None:
        with self._lock:
            return self._latest

    def cpu_sparkline(self, width: int = 8) -> str:
        with self._lock:
            values = list(self._cpu_history)
        return sparkline(values, width)

    def cpu_values(self) -> list[float]:
        with self._lock:
            return list(self._cpu_history)

    def recent_surges(self) -> list[SurgeEvent]:
        with self._lock:
            return list(self._surge_history)

    def record_surge(self, summary: str) -> None:
        with self._lock:
            self._surge_history.append(SurgeEvent(ts=time.time(), summary=summary))

    def is_stalled(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            last_ok = self._last_ok
            paused = self._paused
        if paused or last_ok == 0.0:
            return False
        return (now - last_ok) > (self.poll_interval * 3)

    # ── pause control ────────────────────────────────────────────────────────

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, value: bool) -> None:
        with self._lock:
            self._paused = value
