from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal


Platform = Literal["darwin", "linux"]


class Env(ABC):
    """Environment / OS introspection. Pure query capability — methods never
    raise. `get` returns None for missing variables; `platform` returns the
    operating system family; `user_home` returns the current user's home
    directory.

    Platforms other than `darwin` / `linux` are not supported by statectl and
    will surface from `platform()` as a typed Literal — implementations that
    encounter an unknown system should still return the closest match
    (typically `linux`) and let callers' assess_state mark it INVALID.
    """

    @abstractmethod
    def get(self, name: str) -> str | None: ...

    @abstractmethod
    def user_home(self) -> Path: ...

    @abstractmethod
    def platform(self) -> Platform: ...
