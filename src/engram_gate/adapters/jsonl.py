"""JSONL store adapter. Implements list_visible(since) per SPEC.md Section 6."""
from __future__ import annotations

import datetime
import json
import os


def _parse_ts(value) -> datetime.datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except ValueError:
        return None


class JsonlAdapter:
    """Reads entries from a JSONL file, or from corpus.jsonl + traces.jsonl
    inside a directory."""

    def __init__(self, path: str):
        self.path = path

    def _files(self) -> list[str]:
        if os.path.isdir(self.path):
            files = []
            for name in ("corpus.jsonl", "traces.jsonl"):
                candidate = os.path.join(self.path, name)
                if os.path.exists(candidate):
                    files.append(candidate)
            if not files:
                raise FileNotFoundError(f"no corpus.jsonl/traces.jsonl in directory: {self.path}")
            return files
        return [self.path]

    def _load_file(self, path: str) -> list[dict]:
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def list_visible(self, since: datetime.datetime | None = None) -> list[dict]:
        entries: list[dict] = []
        for path in self._files():
            entries.extend(self._load_file(path))
        if since is None:
            return entries
        visible = []
        for e in entries:
            ts = _parse_ts(e.get("ts"))
            # Entries without a parseable ts cannot be aged out; keep visible.
            if ts is None or ts >= since:
                visible.append(e)
        return visible
