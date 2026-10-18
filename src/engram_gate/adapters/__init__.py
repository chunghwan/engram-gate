"""Store adapters (SPEC.md Section 6)."""
from .jsonl import JsonlAdapter
from .sqlite import SqliteAdapter

__all__ = ["JsonlAdapter", "SqliteAdapter"]
