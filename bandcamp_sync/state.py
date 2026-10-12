"""The sync record: which purchases are already downloaded, per format."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_NAME = ".bandcamp-sync.json"


def state_key(sale_key: str, fmt: str) -> str:
    return f"{sale_key}:{fmt}"


class State:
    def __init__(self, path: Path, entries: dict | None = None):
        self.path = path
        self.entries: dict[str, dict] = entries or {}

    @classmethod
    def load(cls, output: Path) -> "State":
        path = output / STATE_NAME
        if not path.exists():
            return cls(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path} isn't a sync record")
        return cls(path, data)

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def record(self, key: str, artist: str, title: str, path: str) -> None:
        self.entries[key] = {
            "artist": artist,
            "title": title,
            "path": path,
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.save()

    def save(self) -> None:
        """Write atomically: a temporary file next to the record, then rename over it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".bandcamp-sync.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
