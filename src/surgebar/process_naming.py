"""Map low-level process names to user-recognizable app names.

A process like 'com.apple.WebKit.GPU' or 'Cursor Helper (Renderer)' is hard for
a user to act on. This module finds the parent .app bundle and returns its
CFBundleName ('Safari', 'Cursor', ...) so the menu shows something the user
actually recognizes.

Strategy:
1. Walk the process executable path upward looking for a '.app' bundle.
2. Read CFBundleName from the bundle's Info.plist via stdlib plistlib.
3. Fall back to a static map for kernel/system processes that aren't .app bundles.
4. Cache by exe path so we don't re-read plists every poll cycle.
"""

from __future__ import annotations

import plistlib
from functools import lru_cache
from pathlib import Path

import psutil

# Kernel and daemon processes that aren't .app bundles but are common surge culprits.
# Maps the psutil process name to a friendly explanation.
SYSTEM_PROCESS_NAMES: dict[str, str] = {
    "kernel_task":         "macOS Kernel",
    "WindowServer":        "Window Server (display)",
    "loginwindow":         "Login Window",
    "Finder":              "Finder",
    "Dock":                "Dock",
    "SystemUIServer":      "Menu Bar / System UI",
    "coreaudiod":          "Core Audio",
    "powerd":              "Power Management",
    "configd":             "System Configuration",
    "syslogd":             "System Log",
    "mDNSResponder":       "Bonjour / DNS",
    "launchd":             "launchd (init)",

    # Spotlight & indexing
    "mds":                 "Spotlight indexing",
    "mds_stores":          "Spotlight indexing",
    "mdworker":            "Spotlight worker",
    "mdworker_shared":     "Spotlight worker",
    "corespotlightd":      "Spotlight",

    # Photos & media indexing
    "photoanalysisd":      "Photos library analysis",
    "mediaanalysisd":      "Media analysis",
    "photolibraryd":       "Photos library",

    # Time Machine / backup
    "backupd":             "Time Machine backup",

    # Network / VPN
    "trustd":              "Certificate validation",
    "networkserviceproxy": "Network proxy",
    "nehelper":            "Network Extension helper",

    # iCloud / File Provider
    "bird":                "iCloud Drive sync",
    "cloudd":              "iCloud daemon",
    "fileproviderd":       "File Provider (iCloud/Dropbox/etc.)",
    "FileProvider":        "File Provider",

    # Antivirus / security (common CPU hogs)
    "XProtect":            "macOS XProtect (antivirus)",
    "XprotectService":     "macOS XProtect (antivirus)",
    "syspolicyd":          "Gatekeeper / security policy",
    "appleeventsd":        "AppleEvents",

    # Common runtimes
    "WindowManager":       "Stage Manager",
    "controlcenter":       "Control Center",
    "Notification Center": "Notification Center",
}


def _find_app_bundle(executable_path: str) -> Path | None:
    """Walk up from an executable path looking for a .app bundle."""
    if not executable_path:
        return None
    path = Path(executable_path)
    for ancestor in path.parents:
        if ancestor.suffix == ".app":
            return ancestor
        # Stop at filesystem root or once we leave /Applications, /System, etc.
        if ancestor in (Path("/"), Path.home()):
            return None
    return None


def _read_bundle_name(app_bundle_path: Path) -> str | None:
    """Read CFBundleName (or CFBundleDisplayName) from an .app bundle's Info.plist."""
    info_plist_path = app_bundle_path / "Contents" / "Info.plist"
    if not info_plist_path.is_file():
        return None
    try:
        with info_plist_path.open("rb") as plist_file:
            plist_data = plistlib.load(plist_file)
    except (OSError, plistlib.InvalidFileException):
        return None
    display_name = plist_data.get("CFBundleDisplayName")
    bundle_name = plist_data.get("CFBundleName")
    name = display_name or bundle_name
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


@lru_cache(maxsize=512)
def _bundle_name_for_executable(executable_path: str) -> str | None:
    bundle = _find_app_bundle(executable_path)
    if bundle is None:
        return None
    return _read_bundle_name(bundle)


def friendly_app_name(pid: int, process_name: str) -> str | None:
    """Return a user-recognizable app/activity name for a process.

    Returns None if no friendly name can be determined (caller should fall back
    to the raw process_name).
    """
    if process_name in SYSTEM_PROCESS_NAMES:
        return SYSTEM_PROCESS_NAMES[process_name]
    try:
        executable_path = psutil.Process(pid).exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return None
    if not executable_path:
        return None
    return _bundle_name_for_executable(executable_path)


def display_label(pid: int, process_name: str, max_chars: int = 28) -> str:
    """Build the short label shown in the menu bar dropdown.

    - If we know the friendly app name and it differs from process_name, show both:
      'Cursor — Helper (Renderer)'
    - If they match (or no friendly name), just show the process name.
    - Truncates to max_chars with an ellipsis.
    """
    friendly = friendly_app_name(pid, process_name)
    if friendly and friendly.lower() != (process_name or "").lower():
        # Collapse very long combined labels by trimming the process_name tail.
        budget_for_process = max_chars - len(friendly) - 3  # "— "
        if budget_for_process >= 8:
            tail = process_name or ""
            if len(tail) > budget_for_process:
                tail = tail[: budget_for_process - 1] + "…"
            return f"{friendly} — {tail}"
        # Friendly name alone is already long; show it and truncate.
        return _truncate(friendly, max_chars)
    return _truncate(process_name or "?", max_chars)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"
