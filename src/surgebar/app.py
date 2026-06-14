"""Menu bar app — thin UI over the background Monitor.

The golden rule of this file: the main (UI) thread does NO blocking work. All
sampling lives in monitor.py on a background thread. The ``update()`` timer here
only reads the latest precomputed snapshot and paints strings, so the menu stays
responsive even when the machine is on fire — which is the whole point of a
surge monitor. The one network call (LLM triage) runs on its own daemon thread.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
from datetime import datetime
from typing import Any

import psutil
import rumps

from . import config
from .diagnose import call_llm, ping_llm, sanitize_actions
from .monitor import Monitor
from .process_naming import friendly_app_name
from .signals import PROTECTED_PROCESSES, gather_system_snapshot

# ─── Tunables ────────────────────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = 5

PROCESS_LIST_SLOTS = 6
ACTION_SLOTS = 3
DIAGNOSE_REPEAT_SUPPRESSION_SECONDS = 90
RECENT_SURGES_SLOTS = 8


class SurgebarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Surgebar", title="🟢 --", quit_button=None)
        self._was_surging_last_tick = False
        self._top_process_pids: list[int | None] = [None] * PROCESS_LIST_SLOTS

        self._settings = config.load_settings()

        self._monitor = Monitor(poll_interval=POLL_INTERVAL_SECONDS, process_slots=PROCESS_LIST_SLOTS)

        self._claude_actions: list[dict[str, Any]] = []
        self._diagnose_in_progress = False
        self._last_diagnose_key: tuple[str, ...] | None = None
        self._last_diagnose_at = 0.0
        self._last_surge_render_count = -1

        self._health_item = rumps.MenuItem("● Starting…", callback=None)
        self._status_item = rumps.MenuItem(self._status_text(), callback=None)
        self._diagnose_now_item = rumps.MenuItem("Diagnose now", callback=self._on_diagnose_now_clicked)
        self._pause_item = rumps.MenuItem("Pause monitoring", callback=self._on_toggle_pause_clicked)
        self._action_menu_items = [
            rumps.MenuItem(f"action_slot_{i}", callback=self._make_action_handler(i))
            for i in range(ACTION_SLOTS)
        ]
        self._process_menu_items = [
            rumps.MenuItem(f"process_slot_{i}", callback=self._make_kill_handler(i))
            for i in range(PROCESS_LIST_SLOTS)
        ]
        self._recent_surges_submenu = rumps.MenuItem("Recent surges")
        self._config_status_item = rumps.MenuItem("…", callback=None)
        self._service_menu_items_by_id: dict[str, rumps.MenuItem] = {}
        self._service_submenu = self._build_service_submenu()
        self._model_menu_items_by_id: dict[str, rumps.MenuItem] = {}
        self._model_submenu = self._build_model_submenu()
        self._apikey_submenu = self._build_apikey_submenu()
        self._endpoint_item = rumps.MenuItem("Endpoint", callback=self._on_set_base_url_clicked)
        self._alert_sound_menu_items_by_id: dict[str, rumps.MenuItem] = {}
        self._alert_sound_submenu = self._build_alert_sound_submenu()
        self._ai_connection_submenu = self._build_ai_connection_submenu()
        self._alerts_submenu = self._build_alerts_submenu()
        self._refresh_config_status()

        self.menu = [
            self._health_item,
            None,
            rumps.MenuItem("── Recommended actions ──", callback=None),
            self._status_item,
            *self._action_menu_items,
            None,
            self._diagnose_now_item,
            None,
            rumps.MenuItem("── Top processes (click to kill) ──", callback=None),
            *self._process_menu_items,
            None,
            self._recent_surges_submenu,
            self._pause_item,
            None,
            self._ai_connection_submenu,
            self._alerts_submenu,
            None,
            rumps.MenuItem("Reveal config in Finder", callback=self._on_reveal_config_clicked),
            rumps.MenuItem("About surgebar", callback=self._on_about_clicked),
            rumps.MenuItem("Quit Surgebar", callback=lambda _: rumps.quit_application()),
        ]

        self._refresh_action_items()
        self._refresh_recent_surges_submenu(force=True)
        self._sync_diagnose_now_enabled()
        self._monitor.start()

        # Custom popover panel. Built defensively: if AppKit setup throws, we keep
        # the plain native menu and the app is unaffected.
        try:
            from .popover import PopoverController
            self._popover_ctrl = PopoverController.alloc().initWithApp_(self)
        except Exception:
            self._popover_ctrl = None
        self._popover_wired = False

    # ── Status helpers ──────────────────────────────────────────────────────

    def _status_text(self) -> str:
        if not self._settings.diagnose_enabled:
            return "Set API key to enable AI triage →"
        return "Diagnose: ready"

    def _sync_diagnose_now_enabled(self) -> None:
        self._diagnose_now_item.set_callback(
            self._on_diagnose_now_clicked if self._settings.diagnose_enabled else None
        )

    # ── Menu construction ───────────────────────────────────────────────────

    def _build_service_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("Service")
        for service_id in config.SERVICE_ORDER:
            if service_id == config.SERVICE_CUSTOM:
                submenu.add(None)
            item = rumps.MenuItem(
                self._service_menu_label(service_id),
                callback=self._make_service_picker_handler(service_id),
            )
            self._service_menu_items_by_id[service_id] = item
            submenu.add(item)
        return submenu

    def _service_menu_label(self, service_id: str) -> str:
        check = "● " if service_id == self._settings.service else "○ "
        return f"{check}{config.SERVICE_PRESETS[service_id]['name']}"

    def _refresh_service_submenu_labels(self) -> None:
        for service_id, item in self._service_menu_items_by_id.items():
            item.title = self._service_menu_label(service_id)

    def _refresh_config_status(self) -> None:
        s = self._settings
        self._config_status_item.title = (
            "● Connected" if s.diagnose_enabled else "○ Not configured — set an API key"
        )
        self._service_submenu.title = f"Service:  {s.service_name}"
        self._model_submenu.title = f"Model:  {s.model}"
        self._apikey_submenu.title = f"API key:  {'✓ set' if s.api_key else 'not set'}"
        self._endpoint_item.title = f"Endpoint:  {s.base_url}"

    def _prompt_base_url(self, service_name: str, default: str = "") -> str | None:
        window = rumps.Window(
            title=f"Base URL for {service_name}",
            message=(
                "Enter the API base URL for this service.\n\n"
                "Don't include /v1/messages or /v1/chat/completions — surgebar appends those.\n"
                "Examples:\n"
                "  • Azure-hosted Anthropic: https://<resource>.services.ai.azure.com/anthropic\n"
                "  • Self-hosted vLLM/LiteLLM: http://localhost:8000"
            ),
            default_text=default,
            ok="Save",
            cancel="Cancel",
            dimensions=(420, 24),
        )
        response = window.run()
        if not response.clicked:
            return None
        return response.text.strip() or None

    def _make_service_picker_handler(self, service_id: str):
        def handler(_: rumps.MenuItem) -> None:
            preset = config.SERVICE_PRESETS[service_id]
            service_name = preset["name"]
            if service_id == config.SERVICE_CUSTOM:
                url = self._prompt_base_url("Custom (OpenAI-compatible)", self._settings.base_url)
                if not url:
                    return
                config.save_custom_service(config.PROVIDER_OPENAI, url)
            elif preset["needs_url"]:
                default = self._settings.base_url if self._settings.service == service_id else ""
                url = self._prompt_base_url(service_name, default)
                if not url:
                    return
                config.save_service(service_id, base_url_override=url)
            else:
                config.save_service(service_id)
            self._settings = config.load_settings()
            self._refresh_service_submenu_labels()
            self._populate_model_submenu(self._model_submenu)
            self._refresh_config_status()
            self._sync_diagnose_now_enabled()
            # If this protocol has no key yet, walk the user straight into setting one.
            if not self._settings.api_key:
                self._on_set_api_key_clicked(None)
        return handler

    def _on_test_connection_clicked(self, _: rumps.MenuItem) -> None:
        if not self._settings.diagnose_enabled:
            rumps.alert(
                title="No API key set",
                message="Pick a Service and set an API key first, then test the connection.",
            )
            return
        self._config_status_item.title = "Testing connection…"
        threading.Thread(target=self._run_test_connection, daemon=True).start()

    def _run_test_connection(self) -> None:
        ok, detail = ping_llm(
            provider=self._settings.provider,
            api_key=self._settings.api_key or "",
            base_url=self._settings.base_url,
            model=self._settings.model,
        )
        self._refresh_config_status()
        if ok:
            rumps.notification(
                title="surgebar — AI connection OK",
                subtitle=f"{self._settings.service_name} · {self._settings.model}",
                message=f"Endpoint replied: {detail}",
                sound=False,
            )
        else:
            rumps.notification(
                title="surgebar — AI connection failed",
                subtitle=f"{self._settings.service_name} · {self._settings.model}",
                message=detail,
                sound=False,
            )

    def _build_model_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("Model")
        self._populate_model_submenu(submenu)
        return submenu

    def _populate_model_submenu(self, submenu: rumps.MenuItem) -> None:
        for key in list(submenu.keys()):
            del submenu[key]
        self._model_menu_items_by_id.clear()
        presets = config.models_for_service(self._settings.service)
        for model_id in presets:
            item = rumps.MenuItem(
                self._model_menu_label(model_id),
                callback=self._make_model_picker_handler(model_id),
            )
            self._model_menu_items_by_id[model_id] = item
            submenu.add(item)
        if self._settings.model not in presets:
            # Show the custom model the user set as already-selected.
            item = rumps.MenuItem(
                self._model_menu_label(self._settings.model),
                callback=self._make_model_picker_handler(self._settings.model),
            )
            self._model_menu_items_by_id[self._settings.model] = item
            submenu.add(item)
        submenu.add(None)
        submenu.add(rumps.MenuItem("Enter custom model…", callback=self._on_custom_model_clicked))

    def _model_menu_label(self, model_id: str) -> str:
        check = "● " if model_id == self._settings.model else "○ "
        return f"{check}{model_id}"

    def _refresh_model_submenu_labels(self) -> None:
        for model_id, item in self._model_menu_items_by_id.items():
            item.title = self._model_menu_label(model_id)

    def _build_ai_connection_submenu(self) -> rumps.MenuItem:
        # One bounded region for everything about reaching the AI. Each row's
        # title carries its current value (set in _refresh_config_status), so the
        # whole setup reads at a glance instead of hiding behind each submenu.
        submenu = rumps.MenuItem("AI connection")
        submenu.add(self._config_status_item)
        submenu.add(None)
        submenu.add(self._service_submenu)
        submenu.add(self._model_submenu)
        submenu.add(self._apikey_submenu)
        submenu.add(self._endpoint_item)
        submenu.add(None)
        submenu.add(rumps.MenuItem("Test connection…", callback=self._on_test_connection_clicked))
        return submenu

    def _build_apikey_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("API key")
        submenu.add(rumps.MenuItem("Set / replace…", callback=self._on_set_api_key_clicked))
        submenu.add(rumps.MenuItem("Remove", callback=self._on_remove_api_key_clicked))
        return submenu

    def _build_alerts_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("Alerts")
        submenu.add(self._alert_sound_submenu)
        submenu.add(rumps.MenuItem("Send test notification", callback=self._on_test_notification_clicked))
        return submenu

    def _build_alert_sound_submenu(self) -> rumps.MenuItem:
        submenu = rumps.MenuItem("Alert sound")
        choices_with_separators: list[str | None] = [
            config.ALERT_SOUND_DEFAULT,
            config.ALERT_SOUND_SILENT,
            None,
            *config.MACOS_SYSTEM_SOUNDS,
        ]
        for choice in choices_with_separators:
            if choice is None:
                submenu.add(None)
                continue
            item = rumps.MenuItem(
                self._alert_sound_menu_label(choice),
                callback=self._make_alert_sound_picker_handler(choice),
            )
            self._alert_sound_menu_items_by_id[choice] = item
            submenu.add(item)
        return submenu

    def _alert_sound_menu_label(self, choice: str) -> str:
        check = "● " if choice == self._settings.alert_sound else "○ "
        display = {
            config.ALERT_SOUND_DEFAULT: "Default (system notification)",
            config.ALERT_SOUND_SILENT: "Silent",
        }.get(choice, choice)
        return f"{check}{display}"

    def _refresh_alert_sound_submenu_labels(self) -> None:
        for choice, item in self._alert_sound_menu_items_by_id.items():
            item.title = self._alert_sound_menu_label(choice)

    def _make_alert_sound_picker_handler(self, choice: str):
        def handler(_: rumps.MenuItem) -> None:
            config.save_alert_sound(choice)
            self._settings = config.load_settings()
            self._refresh_alert_sound_submenu_labels()
            self._preview_alert_sound()
        return handler

    def _preview_alert_sound(self) -> None:
        if self._settings.alert_sound == config.ALERT_SOUND_SILENT:
            return
        if self._settings.alert_sound == config.ALERT_SOUND_DEFAULT:
            return
        self._play_system_sound(self._settings.alert_sound)

    def _play_system_sound(self, name: str) -> None:
        path = f"/System/Library/Sounds/{name}.aiff"
        if not os.path.exists(path):
            return
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _emit_alert_notification(self, title: str, subtitle: str, message: str) -> None:
        sound_setting = self._settings.alert_sound
        if sound_setting == config.ALERT_SOUND_DEFAULT:
            rumps.notification(title=title, subtitle=subtitle, message=message, sound=True)
            return
        rumps.notification(title=title, subtitle=subtitle, message=message, sound=False)
        if sound_setting != config.ALERT_SOUND_SILENT:
            self._play_system_sound(sound_setting)

    def _on_test_notification_clicked(self, _: rumps.MenuItem) -> None:
        self._emit_alert_notification(
            title="surgebar — test notification",
            subtitle="If you see this, the alert path works.",
            message="Real surge alerts trigger when CPU ≥85% or load-per-core ≥2.0.",
        )

    # ── Pause control ─────────────────────────────────────────────────────────

    def _on_toggle_pause_clicked(self, _: rumps.MenuItem) -> None:
        now_paused = not self._monitor.paused
        self._monitor.set_paused(now_paused)
        self._pause_item.title = "Resume monitoring" if now_paused else "Pause monitoring"
        if now_paused:
            self.title = "⏸ paused"

    # ── Recent surges ─────────────────────────────────────────────────────────

    def _refresh_recent_surges_submenu(self, force: bool = False) -> None:
        surges = self._monitor.recent_surges()
        if not force and len(surges) == self._last_surge_render_count:
            return
        self._last_surge_render_count = len(surges)
        for key in list(self._recent_surges_submenu.keys()):
            del self._recent_surges_submenu[key]
        if not surges:
            self._recent_surges_submenu.add(rumps.MenuItem("No surges this session", callback=None))
            return
        for event in reversed(list(surges)[-RECENT_SURGES_SLOTS:]):
            stamp = datetime.fromtimestamp(event.ts).strftime("%H:%M")
            self._recent_surges_submenu.add(rumps.MenuItem(f"{stamp}  {event.summary}", callback=None))

    # ── Action rendering ────────────────────────────────────────────────────

    def _refresh_action_items(self) -> None:
        kind_prefix = {"throttle": "↓", "quit": "⏏", "kill": "✕", "info": "ⓘ"}
        for index, item in enumerate(self._action_menu_items):
            if index < len(self._claude_actions):
                action = self._claude_actions[index]
                prefix = kind_prefix.get(action.get("kind"), "•")
                label = (action.get("label") or "?")[:60]
                item.title = f"  {prefix} {label}"
                self._set_item_hidden(item, False)
            else:
                item.title = ""
                self._set_item_hidden(item, True)  # no blank gap when there are no actions

    def _set_item_hidden(self, item, hidden: bool) -> None:
        with contextlib.suppress(Exception):
            item._menuitem.setHidden_(hidden)

    # ── Diagnose flow ───────────────────────────────────────────────────────

    def _maybe_diagnose(self, culprit_signature: tuple[str, ...], force: bool = False) -> None:
        if not self._settings.diagnose_enabled or self._diagnose_in_progress:
            return
        now = time.time()
        if (
            not force
            and culprit_signature == self._last_diagnose_key
            and (now - self._last_diagnose_at) < DIAGNOSE_REPEAT_SUPPRESSION_SECONDS
        ):
            return
        self._diagnose_in_progress = True
        self._status_item.title = "Diagnose: thinking…"
        threading.Thread(
            target=self._run_diagnose_in_background,
            args=(culprit_signature,),
            daemon=True,
        ).start()

    def _run_diagnose_in_background(self, culprit_signature: tuple[str, ...]) -> None:
        try:
            assert self._settings.api_key is not None  # diagnose_enabled gate
            snapshot = gather_system_snapshot()  # heavy enrichment — off the UI thread
            raw = call_llm(
                snapshot,
                provider=self._settings.provider,
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                model=self._settings.model,
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
        snapshot = self._monitor.latest
        signature = tuple(r.name for r in snapshot.rows[:3]) if snapshot else ()
        self._maybe_diagnose(signature, force=True)

    # ── Configuration handlers ──────────────────────────────────────────────

    def _on_set_api_key_clicked(self, _: rumps.MenuItem) -> None:
        provider_display = config.PROVIDER_DISPLAY_NAMES[self._settings.provider]
        existing = "(saved in Keychain)" if self._settings.api_key else ""
        window = rumps.Window(
            title=f"Set API key — {provider_display}",
            message=(
                f"Paste your API key for the currently selected provider ({provider_display}).\n\n"
                f"Stored securely in macOS Keychain under service "
                f"'surgebar:{self._settings.provider}-api-key'.\n\n"
                "Switch providers via Configuration → Provider."
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
            config.save_api_key(self._settings.provider, api_key)
        except subprocess.CalledProcessError as error:
            rumps.alert(
                title="Could not save key",
                message=(error.stderr or b"").decode() or str(error),
            )
            return
        self._settings = config.load_settings()
        self._status_item.title = self._status_text()
        self._sync_diagnose_now_enabled()
        self._refresh_config_status()
        rumps.notification(
            title="surgebar",
            subtitle="API key saved",
            message=f"AI triage enabled via {provider_display}.",
            sound=False,
        )

    def _on_remove_api_key_clicked(self, _: rumps.MenuItem) -> None:
        if not self._settings.api_key:
            rumps.alert(title="No key to remove", message="There's no API key configured for the current provider.")
            return
        provider_display = config.PROVIDER_DISPLAY_NAMES[self._settings.provider]
        if rumps.alert(
            title=f"Remove API key for {provider_display}?",
            message="The key will be deleted from macOS Keychain. AI triage will be disabled until a new key is set.",
            ok="Remove",
            cancel="Cancel",
        ) != 1:
            return
        config.clear_api_key(self._settings.provider)
        self._settings = config.load_settings()
        self._claude_actions = []
        self._refresh_action_items()
        self._status_item.title = self._status_text()
        self._sync_diagnose_now_enabled()
        self._refresh_config_status()

    def _on_set_base_url_clicked(self, _: rumps.MenuItem) -> None:
        window = rumps.Window(
            title="Set base URL",
            message=(
                "Override the API base URL (useful for OpenRouter, Groq, local Ollama, Azure-hosted Anthropic, etc.).\n\n"
                "Default for Anthropic protocol: https://api.anthropic.com\n"
                "Default for OpenAI protocol:    https://api.openai.com\n\n"
                "Don't include /v1/messages or /v1/chat/completions — surgebar appends those."
            ),
            default_text=self._settings.base_url,
            ok="Save",
            cancel="Cancel",
            dimensions=(420, 24),
        )
        response = window.run()
        if not response.clicked:
            return
        new_url = response.text.strip()
        if not new_url:
            return
        config.save_base_url(new_url)
        self._settings = config.load_settings()
        self._refresh_config_status()

    def _make_model_picker_handler(self, model_id: str):
        def handler(_: rumps.MenuItem) -> None:
            config.save_model(model_id)
            self._settings = config.load_settings()
            self._refresh_model_submenu_labels()
            self._refresh_config_status()
        return handler

    def _on_custom_model_clicked(self, _: rumps.MenuItem) -> None:
        window = rumps.Window(
            title="Enter custom model name",
            message=(
                "Type any model identifier supported by your selected provider.\n\n"
                "Examples for OpenAI-compatible:\n"
                "  • mistral-large-latest\n"
                "  • llama-3.1-70b-instruct\n"
                "  • anthropic/claude-sonnet-4.6 (OpenRouter style)\n"
                "  • qwen2.5-coder:7b (Ollama local)"
            ),
            default_text=self._settings.model,
            ok="Save",
            cancel="Cancel",
            dimensions=(360, 24),
        )
        response = window.run()
        if not response.clicked or not response.text.strip():
            return
        config.save_model(response.text.strip())
        self._settings = config.load_settings()
        self._populate_model_submenu(self._model_submenu)
        self._refresh_config_status()

    def _on_reveal_config_clicked(self, _: rumps.MenuItem) -> None:
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(config.CONFIG_DIR)], check=False)

    def _on_about_clicked(self, _: rumps.MenuItem) -> None:
        from . import ICON_PATH, __version__
        readme_url = "https://github.com/talvinder/surgebar#readme"
        result = rumps.alert(
            title=f"surgebar v{__version__}",
            message=(
                "Menu bar CPU surge alerts with one-click LLM-powered triage.\n\n"
                "Supports Anthropic, OpenAI, Groq, OpenRouter, Together, Mistral,\n"
                "Ollama, LM Studio, and any other Anthropic- or OpenAI-compatible\n"
                "endpoint. Bring your own model.\n\n"
                f"Source & docs: {readme_url}"
            ),
            ok="Open README",
            cancel="Close",
            icon_path=str(ICON_PATH) if ICON_PATH.exists() else None,
        )
        if result == 1:
            subprocess.run(["open", readme_url], check=False)

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

    # ── Main loop (UI thread — read-only, never blocks) ──────────────────────

    @rumps.timer(POLL_INTERVAL_SECONDS)
    def update(self, _: rumps.Timer) -> None:
        self._wire_popover_if_ready()
        # Paused: monitor isn't sampling, so don't render stale data as live.
        if self._monitor.paused:
            self.title = "⏸ paused"
            self._health_item.title = "⏸ Paused — not monitoring"
            return

        # Watchdog: the sampler stalled (system thrashing). Stay honest and stay open.
        if self._monitor.is_stalled():
            self.title = "⚠️ stalled"
            self._health_item.title = "⚠️ Sampling slow — system under heavy load"
            return

        snapshot = self._monitor.latest
        if snapshot is None:
            return  # first sample not in yet

        spark = self._monitor.cpu_sparkline(width=8)
        self.title = f"{snapshot.dot}{spark} {snapshot.cpu_percent:.0f}%  L:{snapshot.load1:.1f}"
        self._health_item.title = (
            f"● Healthy — CPU {snapshot.cpu_percent:.0f}%, load {snapshot.load1:.1f}"
        )

        # Surge edge: fire notification + record history + kick off AI triage.
        if snapshot.surging and not self._was_surging_last_tick:
            summary = ", ".join(
                f"{r.name[:18]} ({r.cpu_percent:.0f}%)" for r in snapshot.rows[:3]
            )
            self._emit_alert_notification(
                title="CPU surge",
                subtitle=f"CPU {snapshot.cpu_percent:.0f}%  |  Load {snapshot.load1:.1f}",
                message=summary,
            )
            self._monitor.record_surge(summary)
            self._maybe_diagnose(tuple(r.name for r in snapshot.rows[:3]))
        self._was_surging_last_tick = snapshot.surging

        # Repaint the kill list from precomputed labels (no syscalls here).
        for index, item in enumerate(self._process_menu_items):
            if index < len(snapshot.rows):
                row = snapshot.rows[index]
                self._top_process_pids[index] = row.pid
                item.title = f"  {row.cpu_percent:5.1f}%  {row.label}"
                self._set_item_hidden(item, False)
            else:
                self._top_process_pids[index] = None
                item.title = ""
                self._set_item_hidden(item, True)

        self._refresh_action_items()
        self._refresh_recent_surges_submenu()

        if self._popover_ctrl is not None:
            with contextlib.suppress(Exception):
                self._popover_ctrl.refresh_if_visible()

    # ── Popover wiring + callbacks ────────────────────────────────────────────

    def _wire_popover_if_ready(self) -> None:
        if self._popover_ctrl is None or self._popover_wired:
            return
        try:
            status_item = getattr(self._nsapp, "nsstatusitem", None)
            if status_item is not None and self._popover_ctrl.wire_status_item(status_item):
                self._popover_wired = True
                print("surgebar: popover armed (left-click = panel, right-click = menu)", flush=True)
        except Exception:
            self._popover_ctrl = None  # give up cleanly; native menu stays

    # Data accessors the panel reads:
    def monitor_snapshot(self):
        return self._monitor.latest

    def monitor_cpu_values(self) -> list[float]:
        return self._monitor.cpu_values()

    def actions(self):
        return list(self._claude_actions[:3])

    def diagnosing(self) -> bool:
        return self._diagnose_in_progress

    # Button clicks from the panel:
    def panel_action(self, kind, payload) -> None:
        if kind == "diagnose":
            self._on_diagnose_now_clicked(None)
            if self._popover_ctrl is not None:  # show "Analyzing…" immediately, not on next tick
                with contextlib.suppress(Exception):
                    self._popover_ctrl.refresh_if_visible()
        elif kind == "settings" and self._popover_ctrl is not None:
            self._popover_ctrl.show_settings_menu()
        elif kind == "kill" and payload is not None:
            self._kill_pid(payload)
        elif kind == "recommend":
            index = payload if isinstance(payload, int) else 0
            self._make_action_handler(index)(None)

    def _kill_pid(self, pid: int) -> None:
        try:
            name = psutil.Process(pid).name()
        except psutil.NoSuchProcess:
            rumps.alert(title="Already gone", message="That process has already exited.")
            return
        if name in PROTECTED_PROCESSES:
            rumps.alert(title="Refused", message=f"{name} is a protected process.")
            return
        if rumps.alert(
            title=f"Kill {name}?",
            message=f"PID {pid}\n\nThis will forcefully terminate the process.",
            ok="Kill it",
            cancel="Cancel",
        ) == 1:
            try:
                os.kill(pid, signal.SIGKILL)
                rumps.notification(
                    title="Process killed", subtitle=name,
                    message=f"PID {pid} terminated.", sound=False,
                )
            except (ProcessLookupError, PermissionError) as error:
                rumps.alert(title="Could not kill", message=str(error))


def _hide_dock_icon() -> None:
    """Convert the running process to a menu-bar-only "accessory" app.

    Only needed when run as a bare Python script (e.g. ``surgebar`` from pipx).
    The packaged .app bundle sets LSUIElement=true in its Info.plist instead, so
    this no-ops harmlessly there.
    """
    try:
        from AppKit import NSApplication  # type: ignore[import-not-found]
        NSApplication.sharedApplication().setActivationPolicy_(1)  # 1 = Accessory
    except ImportError:
        pass


def run_app() -> None:
    _hide_dock_icon()
    SurgebarApp().run()
