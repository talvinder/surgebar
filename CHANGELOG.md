# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased

### Added
- Menu bar CPU and load monitor with 🟢 / 🟡 / 🔴 status dot.
- Native macOS notification when CPU surges past 85% or load-per-core past 2.0.
- Claude-powered triage: top processes sent to the Anthropic API, 1–3 actions returned, sanitized against a protected-process list.
- One-click `renice` / `SIGTERM` / `SIGKILL` actions with confirmation dialogs.
- Top-6 process kill list directly in the menu.
- macOS Keychain storage for the Anthropic API key (no plaintext on disk).
- Model picker submenu (Haiku / Sonnet / Opus).
- `surgebar configure` CLI for headless first-run setup.
- `surgebar status` to inspect current configuration.
- launchd plist template for login auto-start.
