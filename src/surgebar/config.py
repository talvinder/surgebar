"""Configuration: API keys in macOS Keychain, provider+model+base_url in JSON.

Supports two API protocols:
- 'anthropic' — POST {base_url}/v1/messages, x-api-key header (Anthropic, Anthropic-via-Azure, Anthropic-via-Bedrock-proxy).
- 'openai'    — POST {base_url}/v1/chat/completions, Authorization: Bearer (OpenAI, Groq, OpenRouter, Together, Mistral, Fireworks, local Ollama, LM Studio, vLLM, anything OpenAI-compatible).

Each provider has its own Keychain entry so you can keep keys for multiple
providers and switch between them without re-typing.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
SUPPORTED_PROVIDERS = [PROVIDER_ANTHROPIC, PROVIDER_OPENAI]

PROVIDER_DISPLAY_NAMES = {
    PROVIDER_ANTHROPIC: "Anthropic (or Anthropic-compatible)",
    PROVIDER_OPENAI: "OpenAI (or OpenAI-compatible)",
}

DEFAULT_BASE_URLS = {
    PROVIDER_ANTHROPIC: "https://api.anthropic.com",
    PROVIDER_OPENAI: "https://api.openai.com",
}

DEFAULT_MODELS = {
    PROVIDER_ANTHROPIC: "claude-haiku-4-5-20251001",
    PROVIDER_OPENAI: "gpt-5-mini",
}

MODEL_PRESETS = {
    PROVIDER_ANTHROPIC: [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
    ],
    PROVIDER_OPENAI: [
        "gpt-5-mini",
        "gpt-5",
        "o3-mini",
        "llama-3.3-70b-versatile",   # Groq default
        "anthropic/claude-haiku-4.5", # OpenRouter pattern
    ],
}

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Surgebar"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_PROVIDER = PROVIDER_ANTHROPIC


@dataclass
class Settings:
    provider: str
    api_key: str | None
    base_url: str
    model: str

    @property
    def diagnose_enabled(self) -> bool:
        return bool(self.api_key)


def _keychain_service_for(provider: str) -> str:
    return f"surgebar:{provider}-api-key"


def _keychain_read(provider: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", _keychain_service_for(provider), "-w"],
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


def _keychain_write(provider: str, api_key: str) -> None:
    subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a", os.environ.get("USER", "surgebar"),
            "-s", _keychain_service_for(provider),
            "-w", api_key,
            "-U",
        ],
        check=True,
        capture_output=True,
    )


def _keychain_delete(provider: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", _keychain_service_for(provider)],
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


def _env_fallback_api_key(provider: str) -> str | None:
    if provider == PROVIDER_ANTHROPIC:
        return os.environ.get("ANTHROPIC_API_KEY")
    if provider == PROVIDER_OPENAI:
        return os.environ.get("OPENAI_API_KEY")
    return None


def load_settings() -> Settings:
    file_config = _read_config_file()
    provider = file_config.get("provider") or DEFAULT_PROVIDER
    if provider not in SUPPORTED_PROVIDERS:
        provider = DEFAULT_PROVIDER

    api_key = _keychain_read(provider) or _env_fallback_api_key(provider)
    base_url = file_config.get("base_url") or DEFAULT_BASE_URLS[provider]
    model = file_config.get("model") or DEFAULT_MODELS[provider]

    return Settings(
        provider=provider,
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
    )


def save_api_key(provider: str, api_key: str) -> None:
    _keychain_write(provider, api_key.strip())


def clear_api_key(provider: str) -> None:
    _keychain_delete(provider)


def save_provider(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    data = _read_config_file()
    data["provider"] = provider
    # Reset base_url and model to provider defaults if user was on the other provider.
    if data.get("provider") != provider:
        data.pop("base_url", None)
        data.pop("model", None)
    _write_config_file(data)


def save_base_url(base_url: str) -> None:
    data = _read_config_file()
    data["base_url"] = base_url.strip().rstrip("/")
    _write_config_file(data)


def save_model(model: str) -> None:
    data = _read_config_file()
    data["model"] = model.strip()
    _write_config_file(data)
