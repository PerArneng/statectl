from __future__ import annotations

from datetime import datetime
from typing import override

from statectl._interfaces.clock import Clock


class FailingClock(Clock):
    """Wraps another Clock and injects exceptions on specific method calls.
    Clock is a pure-query capability so failures are uncommon, but the wrapper
    is provided for symmetry with the other capabilities.
    """

    def __init__(self, inner: Clock) -> None:
        self._inner = inner
        self._failures: list[tuple[str, BaseException]] = []

    def fail(self, method: str, error: BaseException) -> None:
        self._failures.append((method, error))

    def _maybe_fail(self, method: str) -> None:
        for i, (m, err) in enumerate(self._failures):
            if m == method:
                del self._failures[i]
                raise err

    @override
    def now(self) -> datetime:
        self._maybe_fail("now")
        return self._inner.now()

    @override
    def monotonic(self) -> float:
        self._maybe_fail("monotonic")
        return self._inner.monotonic()
