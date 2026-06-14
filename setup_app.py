"""py2app build for a standalone, menu-bar-only Surgebar.app.

Produces a self-contained .app with its own Python — no pipx, no system Python
needed by the end user. The Info.plist sets LSUIElement=true so macOS treats it
as a menu-bar accessory (no Dock icon, no Cmd-Tab entry) without the runtime
setActivationPolicy hack used in the pipx/script path.

Build:
    pip install -e ".[build]"
    python setup_app.py py2app

Output: dist/Surgebar.app

Then sign + notarize with scripts/notarize.sh, and package with scripts/make_dmg.sh.
"""

from __future__ import annotations

import re
from pathlib import Path

from setuptools import setup

_init_source = (Path(__file__).resolve().parent / "src" / "surgebar" / "__init__.py").read_text()
_version_match = re.search(r'__version__ = "([^"]+)"', _init_source)
__version__ = _version_match.group(1) if _version_match else "0.0.0"

APP = ["scripts/app_entry.py"]
ICON = "src/surgebar/assets/surgebar.icns"

PLIST = {
    "CFBundleName": "Surgebar",
    "CFBundleDisplayName": "Surgebar",
    "CFBundleIdentifier": "com.surgebar.app",
    "CFBundleVersion": __version__,
    "CFBundleShortVersionString": __version__,
    "CFBundleIconFile": "surgebar.icns",
    "LSUIElement": True,  # menu-bar-only: no Dock icon, no Cmd-Tab entry
    "LSMinimumSystemVersion": "12.0",
    "NSHumanReadableCopyright": "MIT License — Talvinder Singh",
    "NSHighResolutionCapable": True,
}

OPTIONS = {
    "argv_emulation": False,
    "iconfile": ICON,
    "plist": PLIST,
    "packages": ["surgebar", "rumps", "psutil"],
    "includes": ["AppKit", "Foundation", "objc", "PyObjCTools"],
    "optimize": 2,
}

setup(
    name="Surgebar",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
