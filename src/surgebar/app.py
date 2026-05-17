"""Menu bar app — surge detection, notifications, Claude triage, click-to-kill."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
from typing import Any

import psutil
import rumps

from . import config
from .diagnose import call_claude, sanitize_actions
from .process_naming import display_label, friendly_app_name
from .signals import (
    CORE_COUNT,
    PROTECTED_PROCESSES,
    gather_system_snapshot,
    top_processes_by_cpu,
)

# ─── Thresholds ─────────────────────────────────────────────────────────────

CPU_WARN_PERCENT = 60
CPU_CRIT_PERCENT = 85
LOAD_PER_CORE_WARN = 1.0
LOAD_PER_CORE_CRIT = 2.0
POLL_INTERVAL_SECONDS = 5

PROCESS_LIST_SLOTS = 6
ACTION_SLOTS = 3
DIAGNOSE_REPEAT_SUPPRESSION_SECONDS = 90


def _status_dot(cpu_percent: float, load1: float) -> str:
    if cpu_percent >= CPU_CRIT_PERCENT or load1 / CORE_COUNT >= LOAD_PER_CORE_CRIT:
        return "🔴"
    if cpu_percent >= CPU_WARN_PERCENT or load1 / CORE_COUNT >= LOAD_PER_CORE_WARN:
        return "🟡"
    return "🟢"


class SurgebarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Surgebar", title="🟢 --")
        self._was_surging_last_tick = False
        self._top_process_pids: list[int | None] = [None] * PROCESS_LIST_SLOTS

        self._settings = config.load_settings()

        self._claude_actions: list[dict[str, Any]] = []
        self._diagnose_in_progress = False
        self._last_diagnose_key: tuple[str, ...] | None = None
        self._last_diagnose_at = 0.0

        self._status_item = rumps.MenuItem(self._status_text(), callback=None)
        self._diagnose_now_item = rumps.MenuItem("Diagnose now", callback=self._on_diagnose_now_clicked)
        self._action_menu_items = [
            rumps.MenuItem(f"action_slot_{i}", callback=self._make_action_handler(i))
            for i in range(ACTION_SLOTS)
        ]
        self._process_menu_items = [
            rumps.MenuItem(f"process_slot_{i}", callback=self._make_kill_handler(i))
            for i in range(PROCESS_LIST_SLOTS)
        ]
        self._model_menu_items_by_id: dict[str, rumps.MenuItem] = {}
        self._model_submenu = self._build_model_submenu()
        self._configuration_submenu = self._build_configuration_submenu()

        self.menu = (
            [
                rumps.MenuItem("── Recommended actions ──", callback=None),
                self._status_item,
            ]
            + self._action_menu_items
            + [
                None,
                self._diagnose_now_item,
                None,
                rumps.MenuItem("── Top processes (click to kill) ──", callback=None),
            ]
            + self._process_menu_items
            + [
                None,
                self._configuration_submenu,
                rumps.MenuItem("Quit Surgebar", callback=lambda _: rumps.quit_application()),
            ]
        )

        self._refresh_action_items()
        self._sync_diagnose_now_enabled()

    # ── Status helpers ──────────────────────────────────────────────────────

    def _status_text(self) -> str:
        if not self._settings.diagnose_enabled:
            return "Set Anthropic API key to enable AI triage →"
        return "Diagnose: ready"

    def _sync_diagnose_now_enabled(self) -> None:
        self._diagnose_now_item.set_callback(
            self._on_diagnose_now_clicked if self._settings.diagnose_enabled else None
        )

    # ── Menu construction ───────────────────────────────────────────────────

    def _build_model_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("Model")
        for model_id in config.SUPPORTED_MODELS:
            item = rumps.MenuItem(
                self._model_menu_label(model_id),
                callback=self._make_model_picker_handler(model_id),
            )
            self._model_menu_items_by_id[model_id] = item
            submenu.add(item)
        return submenu

    def _model_menu_label(self, model_id: str) -> str:
        check = "● " if model_id == self._settings.model else "○ "
        pretty = model_id.replace("-20251001", "")
        return f"{check}{pretty}"

    def _refresh_model_submenu_labels(self) -> None:
        for model_id, item in self._model_menu_items_by_id.items():
            item.title = self._model_menu_label(model_id)

    def _build_configuration_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("Configuration")
        submenu.add(rumps.MenuItem("Set Anthropic API key…", callback=self._on_set_api_key_clicked))
        submenu.add(rumps.MenuItem("Remove API key", callback=self._on_remove_api_key_clicked))
        submenu.add(self._model_submenu)
        submenu.add(None)
        submenu.add(rumps.MenuItem("Reveal config in Finder", callback=self._on_reveal_config_clicked))
        submenu.add(rumps.MenuItem("About surgebar", callback=self._on_about_clicked))
        return submenu

    # ── Action rendering ────────────────────────────────────────────────────

    def _refresh_action_items(self) -> None:
        kind_prefix = {"throttle": "↓", "quit": "⏏", "kill": "✕", "info": "ⓘ"}
        for index, item in enumerate(self._action_menu_items):
            if index < len(self._claude_actions):
                action = self._claude_actions[index]
                prefix = kind_prefix.get(action.get("kind"), "•")
                label = (action.get("label") or "?")[:60]
                item.title = f"  {prefix} {label}"
            else:
                item.title = ""

    # ── Diagnose flow ───────────────────────────────────────────────────────

    def _maybe_diagnose(self, snapshot: dict[str, Any]) -> None:
        if not self._settings.diagnose_enabled or self._diagnose_in_progress:
            return
        culprit_signature = tuple(p["name"] for p in snapshot["processes"][:3])
        now = time.time()
        if (
            culprit_signature == self._last_diagnose_key
            and (now - self._last_diagnose_at) < DIAGNOSE_REPEAT_SUPPRESSION_SECONDS
        ):
            return
        self._diagnose_in_progress = True
        self._status_item.title = "Diagnose: thinking…"
        threading.Thread(
            target=self._run_diagnose_in_background,
            args=(snapshot, culprit_signature),
            daemon=True,
        ).start()

    def _run_diagnose_in_background(
        self,
        snapshot: dict[str, Any],
        culprit_signature: tuple[str, ...],
    ) -> None:
        try:
            assert self._settings.api_key is not None  # diagnose_enabled gate
            raw = call_claude(
                snapshot,
                self._settings.api_key,
                self._settings.base_url,
                self._settings.model,
            )
            actions = sanitize_actions(raw, snapshot)
            self._claude_actions = actions
            self._last_diagnose_key = culprit_signature
            self._last_diagnose_at = time.time()
            self._status_item.title = (
                f"Diagnose: {len(actions)} suggestion(s)" if actions
                else "Diagnose: nothing actionable"
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            self._status_item.title = "Diagnose: network error"
        except (json.JSONDecodeError, ValueError):
            self._status_item.title = "Diagnose: parse error"
        except Exception:
            self._status_item.title = "Diagnose: error"
        finally:
            self._diagnose_in_progress = False

    def _on_diagnose_now_clicked(self, _: rumps.MenuItem) -> None:
        self._last_diagnose_key = None
        self._maybe_diagnose(gather_system_snapshot())

    # ── Configuration handlers ──────────────────────────────────────────────

    def _on_set_api_key_clicked(self, _: rumps.MenuItem) -> None:
        existing = "(saved in Keychain)" if self._settings.api_key else ""
        window = rumps.Window(
            title="Set Anthropic API key",
            message=(
                "Paste your Anthropic API key (starts with sk-ant-…).\n\n"
                "Stored securely in macOS Keychain under service "
                f"'{config.KEYCHAIN_SERVICE}'.\n\n"
                "Get a key at https://console.anthropic.com/settings/keys"
            ),
            default_text=existing,
            ok="Save",
            cancel="Cancel",
            dimensions=(360, 24),
        )
        response = window.run()
        if not response.clicked:
            return
        api_key = response.text.strip()
        if not api_key or api_key == existing:
            return
        try:
            config.save_api_key(api_key)
        except subprocess.CalledProcessError as error:
            rumps.alert(
                title="Could not save key",
                message=(error.stderr or b"").decode() or str(error),
            )
            return
        self._settings = config.load_settings()
        self._status_item.title = self._status_text()
        self._sync_diagnose_now_enabled()
        rumps.notification(
            title="surgebar",
            subtitle="API key saved",
            message="AI triage is now enabled.",
            sound=False,
        )

    def _on_remove_api_key_clicked(self, _: rumps.MenuItem) -> None:
        if not self._settings.api_key:
            rumps.alert(title="No key to remove", message="There's no API key configured.")
            return
        if rumps.alert(
            title="Remove API key?",
            message="The key will be deleted from macOS Keychain. AI triage will be disabled.",
            ok="Remove",
            cancel="Cancel",
        ) != 1:
            return
        config.clear_api_key()
        self._settings = config.load_settings()
        self._claude_actions = []
        self._refresh_action_items()
        self._status_item.title = self._status_text()
        self._sync_diagnose_now_enabled()

    def _make_model_picker_handler(self, model_id: str):
        def handler(_: rumps.MenuItem) -> None:
            config.save_model(model_id)
            self._settings = config.load_settings()
            self._refresh_model_submenu_labels()
        return handler

    def _on_reveal_config_clicked(self, _: rumps.MenuItem) -> None:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(config.CONFIG_DIR)], check=False)

    def _on_about_clicked(self, _: rumps.MenuItem) -> None:
        from . import __version__
        rumps.alert(
            title=f"surgebar v{__version__}",
            message=(
                "Menu bar CPU surge alerts with AI triage.\n\n"
                "github.com/talvinder/surgebar"
            ),
        )

    # ── Action execution ────────────────────────────────────────────────────

    def _make_action_handler(self, slot_index: int):
        def handler(_: rumps.MenuItem) -> None:
            if slot_index >= len(self._claude_actions):
                return
            action = self._claude_actions[slot_index]
            kind = action.get("kind")
            pid = action.get("pid")
            rationale = action.get("rationale") or action.get("label") or ""

            if kind == "info":
                rumps.alert(title="Diagnosis", message=rationale)
                return

            try:
                process_name = psutil.Process(pid).name()
            except psutil.NoSuchProcess:
                rumps.alert(title="Already gone", message=f"PID {pid} no longer exists.")
                self._claude_actions = [a for a in self._claude_actions if a is not action]
                self._refresh_action_items()
                return

            if process_name in PROTECTED_PROCESSES:
                rumps.alert(title="Refused", message=f"{process_name} is a protected process.")
                return

            verb = {"throttle": "Throttle", "quit": "Quit (graceful)", "kill": "Kill (force)"}[kind]
            if rumps.alert(
                title=f"{verb} {process_name}?",
                message=f"PID {pid}\n\n{rationale}",
                ok=verb,
                cancel="Cancel",
            ) != 1:
                return

            try:
                if kind == "throttle":
                    subprocess.run(
                        ["renice", "19", "-p", str(pid)],
                        check=True,
                        capture_output=True,
                    )
                    rumps.notification(
                        title="Throttled",
                        subtitle=process_name,
                        message=f"PID {pid} reniced to 19.",
                        sound=False,
                    )
                elif kind == "quit":
                    os.kill(pid, signal.SIGTERM)
                    rumps.notification(
                        title="Quit signal sent",
                        subtitle=process_name,
                        message=f"PID {pid} (SIGTERM).",
                        sound=False,
                    )
                elif kind == "kill":
                    os.kill(pid, signal.SIGKILL)
                    rumps.notification(
                        title="Process killed",
                        subtitle=process_name,
                        message=f"PID {pid} terminated.",
                        sound=False,
                    )
                self._claude_actions = [a for a in self._claude_actions if a is not action]
                self._refresh_action_items()
            except subprocess.CalledProcessError as error:
                rumps.alert(
                    title="Action failed",
                    message=(error.stderr or b"").decode() or str(error),
                )
            except (ProcessLookupError, PermissionError) as error:
                rumps.alert(title="Action failed", message=str(error))
        return handler

    def _make_kill_handler(self, slot_index: int):
        def handler(_: rumps.MenuItem) -> None:
            pid = self._top_process_pids[slot_index]
            if pid is None:
                return
            try:
                proc = psutil.Process(pid)
                process_name = proc.name()
                cpu_percent = proc.cpu_percent(interval=0.1)
            except psutil.NoSuchProcess:
                rumps.alert(title="Already gone", message="That process has already exited.")
                return
            friendly = friendly_app_name(pid, process_name)
            title_label = f"{friendly} — {process_name}" if friendly and friendly != process_name else process_name
            if rumps.alert(
                title=f"Kill {title_label}?",
                message=(
                    f"PID {pid}  |  CPU {cpu_percent:.1f}%\n\n"
                    "This will forcefully terminate the process."
                ),
                ok="Kill it",
                cancel="Cancel",
            ) == 1:
                try:
                    os.kill(pid, signal.SIGKILL)
                    rumps.notification(
                        title="Process killed",
                        subtitle=process_name,
                        message=f"PID {pid} terminated.",
                        sound=False,
                    )
                except (ProcessLookupError, PermissionError) as error:
                    rumps.alert(title="Could not kill", message=str(error))
        return handler

    # ── Main loop ───────────────────────────────────────────────────────────

    @rumps.timer(POLL_INTERVAL_SECONDS)
    def update(self, _: rumps.Timer) -> None:
        cpu_percent = psutil.cpu_percent(interval=None)
        load1, _, _ = os.getloadavg()
        self.title = f"{_status_dot(cpu_percent, load1)} {cpu_percent:.0f}%  L:{load1:.1f}"

        surging_now = (
            cpu_percent >= CPU_CRIT_PERCENT
            or load1 / CORE_COUNT >= LOAD_PER_CORE_CRIT
        )
        if surging_now and not self._was_surging_last_tick:
            snapshot = gather_system_snapshot()
            top_three_summary = ", ".join(
                f"{p['name'][:18]} ({p['cpu_percent']:.0f}%)"
                for p in snapshot["processes"][:3]
            )
            rumps.notification(
                title="CPU surge",
                subtitle=f"CPU {cpu_percent:.0f}%  |  Load {load1:.1f}",
                message=top_three_summary,
                sound=True,
            )
            self._maybe_diagnose(snapshot)
        self._was_surging_last_tick = surging_now

        top_processes = top_processes_by_cpu(PROCESS_LIST_SLOTS)
        for index, item in enumerate(self._process_menu_items):
            if index < len(top_processes):
                proc = top_processes[index]
                self._top_process_pids[index] = proc["pid"]
                label = display_label(proc["pid"], proc["name"] or "?")
                cpu_for_proc = proc.get("cpu_percent") or 0.0
                item.title = f"  {cpu_for_proc:5.1f}%  {label}"
            else:
                self._top_process_pids[index] = None
                item.title = ""

        self._refresh_action_items()


def run_app() -> None:
    psutil.cpu_percent(interval=1)  # prime the per-process CPU counters
    SurgebarApp().run()
