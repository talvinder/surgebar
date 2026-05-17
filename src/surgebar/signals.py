"""Process and system signal collection via psutil."""

from __future__ import annotations

import os
import time
from typing import Any

import psutil

from .process_naming import friendly_app_name

CORE_COUNT: int = psutil.cpu_count() or 1

# System processes that surgebar will never offer to throttle/kill/quit.
PROTECTED_PROCESSES: frozenset[str] = frozenset({
    "kernel_task", "launchd", "WindowServer", "loginwindow", "Finder",
    "Dock", "Spotlight", "SystemUIServer", "coreaudiod", "powerd",
    "configd", "syslogd", "diskarbitrationd", "mDNSResponder",
    "Python", "python3", "python3.11", "python3.12", "python3.13", "python3.14",
    "surgebar",
})


def top_processes_by_cpu(limit: int) -> list[dict[str, Any]]:
    procs: list[dict[str, Any]] = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "status"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x.get("cpu_percent") or 0.0, reverse=True)
    return procs[:limit]


def enrich_processes(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = time.time()
    enriched: list[dict[str, Any]] = []
    for p in processes:
        try:
            proc = psutil.Process(p["pid"])
            with proc.oneshot():
                cmdline = " ".join(proc.cmdline() or [])[:200]
                memory_mb = proc.memory_info().rss / (1024 * 1024)
                threads = proc.num_threads()
                age_seconds = int(now - proc.create_time())
                try:
                    parent_name = proc.parent().name() if proc.parent() else "?"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    parent_name = "?"
            enriched.append({
                "pid": p["pid"],
                "name": p["name"],
                "app_name": friendly_app_name(p["pid"], p["name"]),
                "cpu_percent": round(p.get("cpu_percent") or 0.0, 1),
                "memory_mb": round(memory_mb, 1),
                "threads": threads,
                "age_seconds": age_seconds,
                "parent": parent_name,
                "cmdline": cmdline,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return enriched


def gather_system_snapshot(top_n: int = 5) -> dict[str, Any]:
    """Returns a snapshot suitable for sending to Claude for triage."""
    enriched = enrich_processes(top_processes_by_cpu(top_n))
    virtual_memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    load1, load5, _ = os.getloadavg()
    return {
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "cores": CORE_COUNT,
            "mem_used_pct": virtual_memory.percent,
            "swap_used_pct": swap.percent,
        },
        "processes": enriched,
    }
