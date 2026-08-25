"""Where files live, which differs between a source checkout and a packaged app.

Two directories matter and they are not the same one:

* **seed** — the operator list and report scope that ship *with* the
  application. Read-only, replaced by every new version.
* **user data** — the decisions and settings this person has made. These must
  outlive an upgrade, and must not be written inside the application folder,
  which on Windows is often somewhere the user cannot write to.

In a source checkout both are ``config/``, so development behaves exactly as
before. In a packaged build the seed comes from inside the bundle and user data
goes to the platform's own location for it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "TAO Report Generator"
REPO_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """The folder the application's own files were unpacked to."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return REPO_ROOT


def seed_config_dir() -> Path:
    """Read-only configuration shipped with the application."""
    return bundle_dir() / "config"


def user_data_dir() -> Path:
    """Where this person's decisions and settings are kept.

    Created on demand. Falls back to the application folder only if the
    platform location cannot be written to, which is better than losing the
    user's decisions entirely.
    """
    if not is_frozen():
        return REPO_ROOT / "config"

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"

    folder = Path(base) / APP_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return bundle_dir() / "config"
    return folder


def user_file(name: str) -> Path:
    return user_data_dir() / name


def resolve_config(name: str) -> Path:
    """The file to read: this person's copy if they have one, else the shipped one."""
    theirs = user_file(name)
    if theirs.exists():
        return theirs
    shipped = seed_config_dir() / name
    return shipped if shipped.exists() else theirs
