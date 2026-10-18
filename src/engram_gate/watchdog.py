"""Per-query watchdog — the enforcement mechanism behind SPEC §8.

SPEC §8: past the latency budget the query MUST escalate to exit 2 on
timeout. This module is how the reference implementation enforces that:
the deterministic query path (adapter read + scoring) runs under a
real-time signal timer. On fire, a QueryTimeout is raised inside the
guarded region; callers map it to exit 2 (CLI) or an exit-2 payload (MCP).

The threshold is a deployment policy value (same class as LIMIT N, SPEC
§4.3); the default equals the §8 budget ceiling (5 s). Where real-time
signals are unavailable — non-POSIX platforms, or a caller on a non-main
thread — the watchdog degrades to a no-op instead of misbehaving; the
caller-side obligation (treat any external timeout as exit 2, SPEC §2)
is unchanged.
"""
from __future__ import annotations

import contextlib
import signal

DEFAULT_TIMEOUT_SECONDS = 5.0


class QueryTimeout(TimeoutError):
    """Raised inside the guarded region when the wall-clock ceiling fires."""


@contextlib.contextmanager
def query_watchdog(seconds: float | None):
    """Raise QueryTimeout if the guarded block exceeds ``seconds``."""
    if seconds is None:
        seconds = DEFAULT_TIMEOUT_SECONDS
    if seconds <= 0:
        raise ValueError("timeout must be a positive number of seconds")
    if not (hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")):
        yield
        return

    def _fire(signum, frame):
        raise QueryTimeout(f"timeout after {seconds:g}s")

    try:
        previous = signal.signal(signal.SIGALRM, _fire)
    except ValueError:  # signal handlers only install on the main thread
        yield
        return
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)
