"""engram-gate: deterministic coordination gate (exit-code contract)."""
from .scoring import score_entry, rank_entries, parse_keywords

__version__ = "0.1.0"
__all__ = ["score_entry", "rank_entries", "parse_keywords", "__version__"]
