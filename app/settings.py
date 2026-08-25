"""Small things the application should remember between runs.

Where the Daily files live, which month was done last, and where reports are
written. Kept beside the other config files, in the same plain-JSON style, and
never version-controlled — it describes one person's machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app import paths

SETTINGS_FILE = "settings.json"


@dataclass
class Settings:
    daily_folder: str = ""
    output_folder: str = ""
    last_period: str = ""  # "YYYYMM"
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        path = Path(path) if path else paths.user_file(SETTINGS_FILE)
        if not path.exists():
            return cls(path=path)
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            # A corrupt settings file must never stop the application starting.
            return cls(path=path)
        return cls(
            daily_folder=str(data.get("daily_folder", "")),
            output_folder=str(data.get("output_folder", "")),
            last_period=str(data.get("last_period", "")),
            path=path,
        )

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else (self.path or paths.user_file(SETTINGS_FILE))
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_notes": (
                "Remembered by the TAO Report Generator: where your Daily files "
                "live, where reports are saved, and the last month you built. "
                "Safe to delete — the application will simply ask again."
            ),
            "daily_folder": self.daily_folder,
            "output_folder": self.output_folder,
            "last_period": self.last_period,
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        self.path = path
        return path

    # --- convenience -------------------------------------------------------

    @property
    def daily_path(self) -> Path | None:
        folder = Path(self.daily_folder) if self.daily_folder else None
        return folder if folder and folder.is_dir() else None

    def remember_period(self, year: int, month: int) -> None:
        self.last_period = f"{year:04d}{month:02d}"

    def suggested_period(self) -> tuple[int, int]:
        """The month to offer: the one after whatever was done last.

        Reports are written monthly, so the next run is almost always the next
        month. Falling back to the month just gone covers a first run.
        """
        if len(self.last_period) == 6 and self.last_period.isdigit():
            year, month = int(self.last_period[:4]), int(self.last_period[4:])
            if 1 <= month <= 12:
                return (year + 1, 1) if month == 12 else (year, month + 1)
        today = date.today()
        previous = date(today.year, today.month, 1)
        return (
            (previous.year - 1, 12) if previous.month == 1 else (previous.year, previous.month - 1)
        )
