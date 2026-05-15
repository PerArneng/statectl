from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import override

from statectl._interfaces.clock import Clock


class RealClock(Clock):
    @override
    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)

    @override
    def monotonic(self) -> float:
        return time.monotonic()
