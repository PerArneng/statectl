from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import override

from statectl._interfaces.clock import Clock


_DEFAULT_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class ScriptedClock(Clock):
    """In-memory clock for tests. `now()` returns the configured wall-clock
    value; `monotonic()` returns a float that advances each call. Use
    `set_now(...)` or `advance(timedelta)` to script the wall clock; use
    `set_monotonic(...)` to script monotonic readings.
    """

    _now: datetime = _DEFAULT_NOW
    _monotonic: float = 0.0
    monotonic_calls: list[float] = field(default_factory=list)

    def set_now(self, value: datetime) -> None:
        self._now = value

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set_monotonic(self, value: float) -> None:
        self._monotonic = value

    @override
    def now(self) -> datetime:
        return self._now

    @override
    def monotonic(self) -> float:
        value = self._monotonic
        self.monotonic_calls.append(value)
        return value
