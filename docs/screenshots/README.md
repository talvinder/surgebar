# Screenshots

Drop demo media here for the README. Suggested set:

| File | Shows |
|------|-------|
| `menu-bar-idle.png` | 🟢 12% L:1.2 in the menu bar — the calm state |
| `menu-bar-surge.png` | 🔴 91% L:8.1 + notification banner |
| `dropdown.png` | Open menu with "Recommended actions" and "Top processes" |
| `configuration.png` | Configuration submenu — "Set Anthropic API key…", model picker, etc. |
| `demo.gif` | 5–10s loop of a real surge → notification → click action → throttle |

## Capture tips

- Use **Cmd+Shift+5** to record. For the GIF, record a `.mov` then convert with `ffmpeg -i in.mov -vf "fps=15,scale=720:-1" -loop 0 demo.gif`.
- Hide other menu bar items via [Bartender](https://www.macbartender.com/) or [Hidden Bar](https://github.com/dwarvesf/hidden) so only surgebar is visible.
- Trigger a real surge for authenticity: `yes > /dev/null & yes > /dev/null & yes > /dev/null &` (kill with `killall yes`).
- Light mode + retina (2x) for crisp README rendering.

## Where they're referenced

Once you drop a file here, link it from the top-level `README.md`. Convention:

```markdown
![surgebar dropdown showing Claude triage suggestions](docs/screenshots/dropdown.png)
```
