from __future__ import annotations

from pathlib import Path
from typing import override

from statectl._interfaces.env import Env, Platform


class FailingEnv(Env):
    """Wraps another Env and injects exceptions on specific method calls.
    Env is a pure-query capability so failures are uncommon, but the wrapper
    is provided for symmetry with the other capabilities.
    """

    def __init__(self, inner: Env) -> None:
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
    def get(self, name: str) -> str | None:
        self._maybe_fail("get")
        return self._inner.get(name)

    @override
    def user_home(self) -> Path:
        self._maybe_fail("user_home")
        return self._inner.user_home()

    @override
    def platform(self) -> Platform:
        self._maybe_fail("platform")
        return self._inner.platform()
