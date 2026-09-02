# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-03

Rewritten as a native macOS app. The Python implementation is preserved on the
`python-legacy` branch and in this repository's history.

### Why
- **The Python version no longer works on macOS 26.** A process without a real
  `.app` bundle can create an `NSStatusItem` that never appears — no error, no
  log line. It ran, reported itself healthy, and put nothing in the menu bar.
  Nothing short of bundling fixes it, so the app is now a bundle.

### Added
- Native SwiftUI `MenuBarExtra` app: CPU + memory ribbon, CPU history sparkline,
  kernel memory-pressure signal, and the top processes with plain-English
  descriptions and per-process actions.
- Bring-your-own-key AI advice over either the Anthropic Messages or OpenAI Chat
  Completions protocol; the key lives in the Keychain and is only ever sent to
  the endpoint you configure. A wrong Service setting now reports the likely
  protocol mismatch instead of a bare 404.
- `scripts/build-app.sh` assembles and ad-hoc signs the app bundle;
  `scripts/install.sh` installs to `/Applications` and starts it at login.
- CI builds the bundle and asserts it is a signed agent app.

### Changed
- Per-process sampling now runs only while the panel is open. At rest the app
  reads two cheap system-wide numbers a second.
- Actions are `setpriority`/`SIGTERM`/`SIGKILL` with plain-English confirmation;
  system processes, and surgebar itself, are refused.

### Fixed
- Panel rendered as a bare header and footer: an unconstrained `ScrollView`
  reports a zero ideal height and `MenuBarExtra` sizes its window from that, so
  the CPU summary, process list and every action were laid out into no space.
- Content drew over the header and footer once AI advice loaded, because sizing
  the `ScrollView` with `fixedSize` stops it clipping. Its content is measured
  and given a definite frame instead.
- An empty Keychain write deleted the stored API key, so a failed read (after
  the app is re-signed, for instance) destroyed it silently. Empty writes are
  ignored; removal is explicit.
- surgebar described itself as "Part of macOS. Best left running."

## [0.2.0] — 2026-07-12

### Changed (architecture)
- **Bulletproof, non-blocking UI.** All sampling — process iteration, `exe()` syscalls, and `Info.plist` disk reads — moved off the UI thread into a dedicated background sampler (`monitor.py`). The menu bar timer now only reads a precomputed, immutable snapshot and paints strings. The menu can no longer freeze when the system is under load, which is exactly when it used to lock up. Root cause of the old freeze: heavy psutil/disk work ran on the rumps main thread during the very surge the app exists to catch.
- The enriched snapshot sent to the LLM is now gathered on the diagnose background thread, not the UI thread.
- Per-PID label cache (60s TTL) avoids re-running `exe()` and re-reading the same `Info.plist` every poll.

### Added
- **Custom surge panel (NSPopover).** Left-clicking the menu bar icon now opens a self-drawn AppKit panel instead of a plain text menu: a status headline with colored dot, a large live CPU%, a CPU-history sparkline graph, a highlighted "Recommended" action band with a one-click Throttle/Quit/Kill button, and the top processes each with a heat-colored CPU bar and a kill control. Built on `NSPopover` so positioning, the arrow, click-outside dismissal, and dark-mode material are native. Right-click (or control-click) the icon for the full configuration menu. Wired defensively — if AppKit setup fails on any machine, the app silently falls back to the native menu. See `popover.py`.
- **Watchdog / graceful degradation.** If the sampler stalls (>3 poll intervals), the menu bar shows "⚠️ stalled" and a "Sampling slow — system under heavy load" status line, but the menu still opens.
- **CPU sparkline** in the menu bar title (recent history at a glance).
- **Health status line** at the top of the menu (healthy / sampling slow / paused).
- **Pause monitoring** toggle — quiet surge alerts during heavy builds, resume in one click.
- **Recent surges** submenu — timestamped log of what's spiked this session.
- **Configuration redesign — one "AI connection" panel.** All the concepts for reaching the AI (service, model, API key, endpoint) are now grouped in a single bounded submenu instead of scattered as flat siblings. Each row shows its current value inline — `Service: Anthropic`, `Model: claude-sonnet-4-6`, `API key: ✓ set`, `Endpoint: …` — so the whole setup reads at a glance (recognition over recall; visibility of system status). A `● Connected / ○ Not configured` line sits on top, **Test connection…** at the bottom. Named **Service** presets (Anthropic, OpenAI, Groq, OpenRouter, Together, Mistral, Ollama, LM Studio, Azure-hosted Anthropic, Custom) auto-fill protocol + base URL + default model — no more manual three-step dance. Alerts (sound, test notification) split into their own submenu. API keys stay keyed by protocol, so existing keys keep working; legacy `provider`+`base_url` configs auto-map to the right service on load.
- **Standalone .app build.** `setup_app.py` (py2app) produces a self-contained, menu-bar-only `Surgebar.app` with `LSUIElement=true` (no runtime Dock-hiding hack). `.icns` app icon, `scripts/notarize.sh` (codesign + notarytool + staple) and `scripts/make_dmg.sh` for distribution to non-Python users.

## [0.1.0] — Unreleased

### Added
- Configurable surge-alert sound. **Configuration → Alert sound** lets you pick "Default", "Silent", or any of the 14 macOS system sounds (Glass, Hero, Ping, Submarine, …). Picking a sound previews it immediately. Persists to `config.json` as `alert_sound`.
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
