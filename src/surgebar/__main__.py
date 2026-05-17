"""Entry point: `surgebar` runs the menu bar app; `surgebar configure` is the CLI setup."""

from __future__ import annotations

import getpass
import subprocess
import sys

from . import __version__, config


def _print_status() -> None:
    settings = config.load_settings()
    print(f"surgebar v{__version__}")
    print(f"Config dir : {config.CONFIG_DIR}")
    print(f"Provider   : {config.PROVIDER_DISPLAY_NAMES[settings.provider]}")
    print(f"Base URL   : {settings.base_url}")
    print(f"Model      : {settings.model}")
    print(f"API key    : {'set (in Keychain)' if settings.api_key else 'NOT SET'}")


def _prompt_provider() -> str:
    print()
    print("Pick a provider:")
    for index, provider_id in enumerate(config.SUPPORTED_PROVIDERS, start=1):
        marker = " (default)" if provider_id == config.DEFAULT_PROVIDER else ""
        print(f"  {index}. {config.PROVIDER_DISPLAY_NAMES[provider_id]}{marker}")
    selection = input(f"Number [default {config.DEFAULT_PROVIDER}]: ").strip()
    if not selection:
        return config.DEFAULT_PROVIDER
    try:
        return config.SUPPORTED_PROVIDERS[int(selection) - 1]
    except (ValueError, IndexError):
        print(f"Invalid selection — using default ({config.DEFAULT_PROVIDER}).")
        return config.DEFAULT_PROVIDER


def _prompt_model(provider: str) -> str:
    presets = config.MODEL_PRESETS[provider]
    default = config.DEFAULT_MODELS[provider]
    print()
    print(f"Pick a model for {config.PROVIDER_DISPLAY_NAMES[provider]}:")
    for index, model_id in enumerate(presets, start=1):
        marker = " (default)" if model_id == default else ""
        print(f"  {index}. {model_id}{marker}")
    print(f"  {len(presets) + 1}. (enter custom)")
    selection = input(f"Number [default {default}]: ").strip()
    if not selection:
        return default
    try:
        index_value = int(selection)
        if 1 <= index_value <= len(presets):
            return presets[index_value - 1]
        if index_value == len(presets) + 1:
            custom = input("Custom model name: ").strip()
            return custom or default
    except ValueError:
        pass
    print(f"Invalid selection — using default ({default}).")
    return default


def _configure() -> int:
    print("Configure surgebar")
    print("==================")
    provider = _prompt_provider()
    config.save_provider(provider)
    print(f"  → provider set to {provider}")

    print()
    print(f"Default base URL: {config.DEFAULT_BASE_URLS[provider]}")
    custom_url = input("Override base URL (Enter to keep default): ").strip()
    if custom_url:
        config.save_base_url(custom_url)
        print(f"  → base URL set to {custom_url}")

    print()
    if provider == config.PROVIDER_ANTHROPIC:
        print("Get an Anthropic API key: https://console.anthropic.com/settings/keys")
    else:
        print("OpenAI-compatible providers include OpenAI, Groq, OpenRouter, Together,")
        print("Mistral, Fireworks, local Ollama (http://localhost:11434), LM Studio, etc.")
    api_key = getpass.getpass("Paste API key (hidden, Enter to skip): ").strip()
    if api_key:
        try:
            config.save_api_key(provider, api_key)
            print("  → API key saved to Keychain")
        except subprocess.CalledProcessError as error:
            sys.stderr.write(f"Could not save key: {(error.stderr or b'').decode() or error}\n")
            return 1
    else:
        print("  → API key not changed (run again or use the menu to set it)")

    model = _prompt_model(provider)
    config.save_model(model)
    print(f"  → model set to {model}")

    print()
    print("Done. Launch the app with: surgebar")
    return 0


def _print_help() -> None:
    print(f"surgebar v{__version__} — menu bar CPU surge alerts with AI triage")
    print()
    print("Usage:")
    print("  surgebar              Run the menu bar app")
    print("  surgebar configure    Interactive setup (provider, API key, model, base URL)")
    print("  surgebar status       Show current configuration")
    print("  surgebar --version    Print version")
    print("  surgebar --help       Show this help")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from .app import run_app
        run_app()
        return 0
    command = args[0]
    if command in {"-h", "--help", "help"}:
        _print_help()
        return 0
    if command in {"-V", "--version", "version"}:
        print(__version__)
        return 0
    if command == "configure":
        return _configure()
    if command == "status":
        _print_status()
        return 0
    if command == "run":
        from .app import run_app
        run_app()
        return 0
    sys.stderr.write(f"Unknown command: {command}\n")
    _print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
