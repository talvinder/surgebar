# surgebar

> Menu bar CPU surge alerts with one-click triage powered by Claude.

surgebar lives in your macOS menu bar. It watches your CPU and load average, fires a notification when things go sideways, and asks Claude what to do about it — then lets you throttle, quit, or kill the culprit with one click.

```
🟢 12%  L:1.2    ← all good
🟡 67%  L:3.4    ← warning
🔴 91%  L:8.1    ← notification fires, Claude triages
```

## Why

Activity Monitor tells you what's hot but not what to do. surgebar tells you the runaway process is `Cursor Helper (Renderer)`, suggests you renice it to 19, and does it in one click. You don't have to remember `kill -9`, `renice`, or which PID to trust.

## Features

- **Surge detection.** Polls every 5s. Notifies on ≥85% CPU or load-per-core ≥2.0.
- **AI triage.** Sends top processes + system signals to Claude, gets back 1–3 ranked actions (throttle / quit / kill / info) with rationales.
- **One-click execution.** `renice 19` for throttle, `SIGTERM` for quit, `SIGKILL` for kill. Every destructive action confirms first.
- **Top-process kill list.** Six hottest processes always in the menu. Click any one to kill it.
- **Protected processes.** Hard-coded refusal to touch `kernel_task`, `WindowServer`, `Finder`, etc. — no matter what Claude recommends.
- **Degraded mode.** Works without an API key — you get surge alerts and the kill list, just no AI suggestions.

## Install

```bash
pipx install surgebar
```

Don't have `pipx`? `brew install pipx && pipx ensurepath`.

## First-run setup

```bash
surgebar configure
```

This prompts for your Anthropic API key and saves it to **macOS Keychain** (service: `surgebar:anthropic-api-key`). No config files contain the key — only your model preference lives in `~/Library/Application Support/Surgebar/config.json`.

Get a key at https://console.anthropic.com/settings/keys. Default model is `claude-haiku-4-5-20251001` (cheap and fast — a surge diagnose is well under a cent).

Don't want to use the CLI? Just launch the app — there's a "Set Anthropic API key…" item in the Configuration submenu.

## Run

```bash
surgebar
```

You'll see a 🟢 emoji and live CPU% in your menu bar. To run it on login, see [Auto-start on login](#auto-start-on-login) below.

## Configuration

| Setting | Where | How to change |
|---------|-------|---------------|
| API key | macOS Keychain | `surgebar configure` or Configuration → Set Anthropic API key… |
| Model | `~/Library/Application Support/Surgebar/config.json` | Configuration → Model → pick one |
| Thresholds (CPU_WARN/CRIT, poll interval) | code constants in `src/surgebar/app.py` | edit and reinstall (configurable thresholds coming) |

You can also set `ANTHROPIC_API_KEY` as an environment variable — it's used as a fallback when no key is in Keychain.

## CLI

```
surgebar              Run the menu bar app
surgebar configure    Save your Anthropic API key + pick a model
surgebar status       Show current configuration
surgebar --version    Print version
```

## Auto-start on login

surgebar ships a launchd plist template at `scripts/com.talvinder.surgebar.plist`. To install:

```bash
# Replace path to your installed surgebar binary
SURGEBAR_BIN=$(which surgebar)
sed "s|__SURGEBAR_BIN__|$SURGEBAR_BIN|" scripts/com.talvinder.surgebar.plist \
  > ~/Library/LaunchAgents/com.talvinder.surgebar.plist
launchctl load ~/Library/LaunchAgents/com.talvinder.surgebar.plist
```

To remove:
```bash
launchctl unload ~/Library/LaunchAgents/com.talvinder.surgebar.plist
rm ~/Library/LaunchAgents/com.talvinder.surgebar.plist
```

## How the AI triage works

When CPU surges, surgebar collects: top 5 processes by CPU (with name, PID, CPU%, mem MB, threads, age, parent, cmdline), plus system load, swap %, memory %. It sends that snapshot to Claude with a prompt that says: "return JSON array of 1–3 actions, never recommend killing protected processes, prefer throttle > quit > kill, suggest 'wait' for known transient indexers."

Claude's response is then **sanitized**: any action targeting a protected process or a non-existent PID is dropped. Even if the model goes off-script, surgebar won't `kill -9 WindowServer`.

Each suggested action is a menu item with a kind prefix:
- `↓` throttle (renice 19)
- `⏏` quit (SIGTERM)
- `✕` kill (SIGKILL)
- `ⓘ` info (just an explanation, no button)

Clicking opens a confirmation alert with the rationale before doing anything.

## Security

- API key lives in macOS Keychain, accessed via the `security` CLI. No plaintext on disk.
- All Anthropic API calls go directly from your Mac to `api.anthropic.com` over TLS. No proxy server. No telemetry.
- surgebar never sends file contents — only process names, PIDs, CPU%, memory MB, thread counts, parent process, and the first 200 chars of cmdline.

## Roadmap

- [ ] Notarized `.dmg` for non-Python users (paid tier, ~$5)
- [ ] Configurable thresholds via UI
- [ ] Pause monitoring (e.g., during builds)
- [ ] Per-process history / "what's been surging this week"
- [ ] Optional local LLM backend (Ollama) so AI triage works offline

## Building from source

```bash
git clone https://github.com/talvinder/surgebar
cd surgebar
pip install -e ".[dev]"
python -m surgebar
```

## License

MIT — see [LICENSE](LICENSE).
