from __future__ import annotations

from pathlib import Path
from typing import override

from statectl._interfaces.hashing import Hashing


class FailingHashing(Hashing):
    """Wraps another Hashing and injects exceptions on `sha256_file`. Use
    `fail(error)` to register a one-shot failure: the next call raises
    `error` instead of delegating. Mirrors the other failing fakes.
    """

    def __init__(self, inner: Hashing) -> None:
        self._inner = inner
        self._failures: list[BaseException] = []

    def fail(self, error: BaseException) -> None:
        self._failures.append(error)

    @override
    def sha256_file(self, path: Path) -> str:
        if self._failures:
            err = self._failures.pop(0)
            raise err
        return self._inner.sha256_file(path)
