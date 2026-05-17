"""Entry point: `surgebar` runs the menu bar app; `surgebar configure` prompts for API key."""

from __future__ import annotations

import getpass
import subprocess
import sys

from . import __version__, config


def _print_status() -> None:
    settings = config.load_settings()
    print(f"surgebar v{__version__}")
    print(f"Config dir : {config.CONFIG_DIR}")
    print(f"Model      : {settings.model}")
    print(f"Base URL   : {settings.base_url}")
    print(f"API key    : {'set (in Keychain)' if settings.api_key else 'NOT SET'}")


def _configure() -> int:
    print("Configure surgebar")
    print("------------------")
    print("Get an Anthropic API key: https://console.anthropic.com/settings/keys")
    print(f"It will be saved to macOS Keychain as service '{config.KEYCHAIN_SERVICE}'.")
    print()
    api_key = getpass.getpass("Paste API key (hidden): ").strip()
    if not api_key:
        print("Aborted. No key entered.")
        return 1
    try:
        config.save_api_key(api_key)
    except subprocess.CalledProcessError as error:
        sys.stderr.write(f"Could not save key: {(error.stderr or b'').decode() or error}\n")
        return 1
    print()
    print("Saved. Available models:")
    for index, model_id in enumerate(config.SUPPORTED_MODELS, start=1):
        marker = " (default)" if model_id == config.DEFAULT_MODEL else ""
        print(f"  {index}. {model_id}{marker}")
    selection = input("Pick model number (Enter for default): ").strip()
    if selection:
        try:
            chosen = config.SUPPORTED_MODELS[int(selection) - 1]
            config.save_model(chosen)
            print(f"Model set to {chosen}.")
        except (ValueError, IndexError):
            print("Invalid selection — keeping default.")
    print()
    print("Done. Launch the app with: surgebar")
    return 0


def _print_help() -> None:
    print(f"surgebar v{__version__} — menu bar CPU surge alerts with AI triage")
    print()
    print("Usage:")
    print("  surgebar              Run the menu bar app")
    print("  surgebar configure    Save your Anthropic API key + pick a model")
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
