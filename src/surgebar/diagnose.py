"""LLM-powered surge triage. Supports two protocols:

- Anthropic Messages API     (POST {base_url}/v1/messages, x-api-key header)
- OpenAI Chat Completions    (POST {base_url}/v1/chat/completions, Bearer token)

OpenAI-compatible mode works with: OpenAI, Groq, OpenRouter, Together,
Mistral, Fireworks, local Ollama (port 11434), LM Studio, vLLM, LiteLLM,
and anything else that speaks the OpenAI chat API.

No SDK dependency — plain urllib + JSON.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
from .signals import PROTECTED_PROCESSES

DIAGNOSE_TIMEOUT_SECONDS = 20
MAX_ACTIONS = 3

PROMPT_TEMPLATE = """You are a macOS performance triage assistant. The user's CPU is surging.
Below is the current system state and the top processes by CPU%.

Each process in the snapshot includes an "app_name" field — the user-recognizable application name (e.g. "Cursor", "Slack", "Spotlight indexing"). Use the app_name when writing the label and rationale so the user knows what they're acting on, even if the process name is cryptic (e.g. "com.apple.WebKit.GPU.xpc").

Recommend 1-3 concrete actions to reduce the surge. Respond with ONLY a JSON array — no prose, no markdown fences.

Each action object has these fields:
- kind: "throttle" (renice to 19, slows it safely), "quit" (SIGTERM, graceful), "kill" (SIGKILL, last resort), or "info" (no action — just inform the user)
- pid: integer process id (null for "info")
- label: short menu label, max 60 chars, prefer the app_name e.g. "Throttle Cursor — Helper (Renderer) — frees ~40% CPU"
- risk: "safe" (clearly leaking helper / well-known runaway) or "confirm" (user-facing app, editor, browser)
- rationale: 1-2 sentences explaining why this helps. Refer to the user-visible app, not the cryptic process name.

Rules:
- NEVER recommend killing/quitting/throttling protected system processes: kernel_task, launchd, WindowServer, loginwindow, Finder, Dock, SystemUIServer, coreaudiod, mDNSResponder, configd, syslogd, powerd, diskarbitrationd, Python/python3 (Python is the monitor itself).
- Prefer "throttle" over "quit" over "kill". Killing is for clearly stuck/unresponsive processes only.
- For known transient indexers (mds, mds_stores, mdworker, photoanalysisd, Spotlight): prefer ONE "info" action telling the user to wait — these self-resolve and killing is counterproductive.
- Ignore processes using <5% CPU.
- If nothing is actionable, return ONE "info" action explaining what's going on.

State:
{payload}
"""


def _call_anthropic(prompt: str, api_key: str, base_url: str, model: str) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(
        base_url + "/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=DIAGNOSE_TIMEOUT_SECONDS) as response:
        response_data = json.loads(response.read())
    return "".join(
        block.get("text", "")
        for block in response_data.get("content", [])
        if block.get("type") == "text"
    ).strip()


def _call_openai(prompt: str, api_key: str, base_url: str, model: str) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(
        base_url + "/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=DIAGNOSE_TIMEOUT_SECONDS) as response:
        response_data = json.loads(response.read())
    choices = response_data.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content", "").strip()


def call_llm(
    snapshot: dict[str, Any],
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
) -> list[dict[str, Any]]:
    """Send a system snapshot to the configured LLM and parse the action list."""
    prompt = PROMPT_TEMPLATE.format(payload=json.dumps(snapshot, indent=2))

    if provider == PROVIDER_ANTHROPIC:
        response_text = _call_anthropic(prompt, api_key, base_url, model)
    elif provider == PROVIDER_OPENAI:
        response_text = _call_openai(prompt, api_key, base_url, model)
    else:
        raise ValueError(f"unknown provider: {provider}")

    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1] if "\n" in response_text else response_text
        response_text = response_text.rsplit("```", 1)[0]
    return json.loads(response_text)


def sanitize_actions(
    raw_actions: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Drop actions referencing protected processes or invalid PIDs."""
    valid_processes = {p["pid"]: p for p in snapshot["processes"]}
    clean: list[dict[str, Any]] = []
    for action in raw_actions or []:
        if not isinstance(action, dict):
            continue
        kind = action.get("kind")
        if kind not in {"throttle", "quit", "kill", "info"}:
            continue
        if kind != "info":
            pid = action.get("pid")
            if pid not in valid_processes:
                continue
            if valid_processes[pid]["name"] in PROTECTED_PROCESSES:
                continue
        clean.append(action)
    return clean[:MAX_ACTIONS]
