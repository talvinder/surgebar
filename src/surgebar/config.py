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

# ─── Named services ──────────────────────────────────────────────────────────
# A "service" is what the user actually thinks in terms of: Groq, Azure, Ollama,
# etc. Each one implies a protocol (provider) and a base URL, so picking a
# service auto-fills both — no more manual protocol + URL dance. The API key
# stays keyed by protocol (see _keychain_service_for) so existing keys keep
# working when you switch between services that share a protocol.

SERVICE_CUSTOM = "custom"

SERVICE_PRESETS: dict[str, dict] = {
    "anthropic": {
        "name": "Anthropic",
        "provider": PROVIDER_ANTHROPIC,
        "base_url": "https://api.anthropic.com",
        "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-7"],
        "needs_url": False,
        "local": False,
    },
    "openai": {
        "name": "OpenAI",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.openai.com",
        "models": ["gpt-5-mini", "gpt-5", "o3-mini"],
        "needs_url": False,
        "local": False,
    },
    "groq": {
        "name": "Groq",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.groq.com/openai",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "needs_url": False,
        "local": False,
    },
    "openrouter": {
        "name": "OpenRouter",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://openrouter.ai/api",
        "models": ["anthropic/claude-haiku-4.5", "openai/gpt-5-mini"],
        "needs_url": False,
        "local": False,
    },
    "together": {
        "name": "Together",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.together.xyz",
        "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
        "needs_url": False,
        "local": False,
    },
    "mistral": {
        "name": "Mistral",
        "provider": PROVIDER_OPENAI,
        "base_url": "https://api.mistral.ai",
        "models": ["mistral-large-latest", "mistral-small-latest"],
        "needs_url": False,
        "local": False,
    },
    "ollama": {
        "name": "Ollama (local)",
        "provider": PROVIDER_OPENAI,
        "base_url": "http://localhost:11434",
        "models": ["qwen2.5-coder:7b", "llama3.1:8b"],
        "needs_url": False,
        "local": True,
    },
    "lmstudio": {
        "name": "LM Studio (local)",
        "provider": PROVIDER_OPENAI,
        "base_url": "http://localhost:1234",
        "models": [],
        "needs_url": False,
        "local": True,
    },
    "azure_anthropic": {
        "name": "Azure (Anthropic)",
        "provider": PROVIDER_ANTHROPIC,
        "base_url": "",  # per-tenant — prompts for the URL when selected
        "models": ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
        "needs_url": True,
        "local": False,
    },
    SERVICE_CUSTOM: {
        "name": "Custom…",
        "provider": PROVIDER_OPENAI,
        "base_url": "",
        "models": [],
        "needs_url": True,
        "local": False,
    },
}

# Display order in the Service submenu.
SERVICE_ORDER = [
    "anthropic", "openai", "groq", "openrouter", "together",
    "mistral", "ollama", "lmstudio", "azure_anthropic", SERVICE_CUSTOM,
]


def _infer_service(provider: str, base_url: str) -> str:
    """Back-compat: derive a service id from a pre-services config (provider+base_url)."""
    normalized = (base_url or "").rstrip("/")
    for service_id in SERVICE_ORDER:
        preset = SERVICE_PRESETS[service_id]
        if preset["needs_url"]:
            continue
        if preset["provider"] == provider and preset["base_url"].rstrip("/") == normalized:
            return service_id
    # Anthropic protocol on a non-default URL ending in /anthropic == Azure-hosted.
    if provider == PROVIDER_ANTHROPIC and normalized.endswith("/anthropic"):
        return "azure_anthropic"
    return SERVICE_CUSTOM


def models_for_service(service_id: str) -> list[str]:
    preset = SERVICE_PRESETS.get(service_id, SERVICE_PRESETS[SERVICE_CUSTOM])
    return list(preset["models"])

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Surgebar"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_PROVIDER = PROVIDER_ANTHROPIC

ALERT_SOUND_DEFAULT = "default"
ALERT_SOUND_SILENT = "silent"

MACOS_SYSTEM_SOUNDS = [
    "Basso", "Blow", "Bottle", "Frog", "Funk", "Glass", "Hero",
    "Morse", "Ping", "Pop", "Purr", "Sosumi", "Submarine", "Tink",
]

ALERT_SOUND_CHOICES = [ALERT_SOUND_DEFAULT, ALERT_SOUND_SILENT, *MACOS_SYSTEM_SOUNDS]


@dataclass
class Settings:
    service: str
    provider: str
    api_key: str | None
    base_url: str
    model: str
    alert_sound: str

    @property
    def diagnose_enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def service_name(self) -> str:
        preset = SERVICE_PRESETS.get(self.service)
        return preset["name"] if preset else self.service

    @property
    def needs_base_url(self) -> bool:
        preset = SERVICE_PRESETS.get(self.service)
        return bool(preset and preset["needs_url"])


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

    base_url = (file_config.get("base_url") or DEFAULT_BASE_URLS[provider]).rstrip("/")

    # Service: explicit if saved, otherwise inferred from the legacy provider+url.
    service = file_config.get("service")
    if service not in SERVICE_PRESETS:
        service = _infer_service(provider, base_url)
    # Keep provider consistent with the resolved service (custom keeps its own).
    if service != SERVICE_CUSTOM:
        provider = SERVICE_PRESETS[service]["provider"]

    api_key = _keychain_read(provider) or _env_fallback_api_key(provider)
    model = file_config.get("model") or DEFAULT_MODELS[provider]
    alert_sound = file_config.get("alert_sound") or ALERT_SOUND_DEFAULT
    if alert_sound not in ALERT_SOUND_CHOICES:
        alert_sound = ALERT_SOUND_DEFAULT

    return Settings(
        service=service,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        alert_sound=alert_sound,
    )


def save_service(service_id: str, base_url_override: str | None = None) -> None:
    """Select a named service: sets protocol, base URL, and default model together."""
    if service_id not in SERVICE_PRESETS:
        raise ValueError(f"unknown service: {service_id}")
    preset = SERVICE_PRESETS[service_id]
    data = _read_config_file()
    data["service"] = service_id
    data["provider"] = preset["provider"]
    if base_url_override:
        data["base_url"] = base_url_override.strip().rstrip("/")
    elif not preset["needs_url"]:
        data["base_url"] = preset["base_url"]
    # else: leave existing base_url; caller will prompt for it.
    models = preset["models"]
    if models:
        data["model"] = models[0]
    _write_config_file(data)


def save_custom_service(provider: str, base_url: str) -> None:
    """Configure the 'Custom…' service with an explicit protocol + base URL."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    data = _read_config_file()
    data["service"] = SERVICE_CUSTOM
    data["provider"] = provider
    data["base_url"] = base_url.strip().rstrip("/")
    _write_config_file(data)


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


def save_alert_sound(alert_sound: str) -> None:
    if alert_sound not in ALERT_SOUND_CHOICES:
        raise ValueError(f"unknown alert sound: {alert_sound}")
    data = _read_config_file()
    data["alert_sound"] = alert_sound
    _write_config_file(data)
