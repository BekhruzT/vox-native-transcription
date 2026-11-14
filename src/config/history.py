"""Keep recent finished transcriptions in history.json beside settings.json."""

import json
import time
from pathlib import Path
from typing import Any

MAX_ENTRIES = 20
RECENT_COUNT = 10
MAX_AGE_SECONDS = 7 * 24 * 3600


class History:
    """Store the newest transcriptions on disk, newest first, within the count and age limits."""

    def __init__(self, folder: Path, enabled: bool = True) -> None:
        """Load saved entries from the folder unless history is disabled."""
        self._file = Path(folder) / "history.json"
        self._enabled = enabled
        self._entries: list[dict[str, Any]] = self._load() if enabled else []

    def _load(self) -> list[dict[str, Any]]:
        """Read valid, unexpired entries and treat any damaged file as empty."""
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        cutoff = time.time() - MAX_AGE_SECONDS
        return [
            entry for entry in data
            if isinstance(entry, dict) and isinstance(entry.get("text"), str) and entry["text"].strip()
            and type(entry.get("time")) in (int, float) and entry["time"] >= cutoff
        ][:MAX_ENTRIES] if isinstance(data, list) else []

    def _save(self) -> None:
        """Write entries to disk, keeping them in memory if the write fails."""
        try:
            self._file.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"[HISTORY] Warning: could not save history: {e}")

    def recent(self) -> list[str]:
        """Return the newest entry texts, newest first."""
        return [entry["text"] for entry in self._entries[:RECENT_COUNT]]

    def add(self, text: str) -> None:
        """Record a finished transcription, ignoring blank text and disabled history."""
        if not self._enabled or not text.strip():
            return
        now = time.time()
        self._entries = [{"text": text, "time": now}, *(entry for entry in self._entries if entry["time"] >= now - MAX_AGE_SECONDS)][:MAX_ENTRIES]
        self._save()

    def clear(self) -> None:
        """Forget every entry in memory and on disk."""
        self._entries = []
        try:
            self._file.unlink(missing_ok=True)
        except OSError as e:
            print(f"[HISTORY] Warning: could not delete history: {e}")

    def set_enabled(self, enabled: bool) -> None:
        """Turn saving on or off; turning it off clears all history."""
        self._enabled = enabled
        if not enabled:
            self.clear()
