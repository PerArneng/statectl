from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """Wall-clock and monotonic time. Pure query capability — methods never
    raise. `now()` returns a timezone-aware UTC `datetime`; `monotonic()`
    returns a float of seconds suitable for elapsed-time measurements but
    not for absolute timestamps.
    """

    @abstractmethod
    def now(self) -> datetime: ...

    @abstractmethod
    def monotonic(self) -> float: ...
