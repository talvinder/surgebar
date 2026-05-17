"""Configuration: API key in macOS Keychain, model preference in JSON."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

KEYCHAIN_SERVICE = "surgebar:anthropic-api-key"
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Surgebar"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SUPPORTED_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-7",
]
ANTHROPIC_BASE_URL = "https://api.anthropic.com"


@dataclass
class Settings:
    api_key: str | None
    base_url: str
    model: str

    @property
    def diagnose_enabled(self) -> bool:
        return bool(self.api_key)


def _keychain_read() -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _keychain_write(api_key: str) -> None:
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            os.environ.get("USER", "surgebar"),
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
            api_key,
            "-U",
        ],
        check=True,
        capture_output=True,
    )


def _keychain_delete() -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE],
        check=False,
        capture_output=True,
    )


def _read_config_file() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_config_file(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def load_settings() -> Settings:
    file_config = _read_config_file()
    api_key = _keychain_read() or os.environ.get("ANTHROPIC_API_KEY")
    base_url = file_config.get("base_url") or ANTHROPIC_BASE_URL
    model = file_config.get("model") or DEFAULT_MODEL
    return Settings(api_key=api_key, base_url=base_url.rstrip("/"), model=model)


def save_api_key(api_key: str) -> None:
    _keychain_write(api_key.strip())


def clear_api_key() -> None:
    _keychain_delete()


def save_model(model: str) -> None:
    data = _read_config_file()
    data["model"] = model
    _write_config_file(data)
