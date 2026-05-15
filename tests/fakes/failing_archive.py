from __future__ import annotations

from pathlib import Path
from typing import override

from statectl._interfaces.archive import (
    Archive,
    ArchiveError,
    ArchiveFormat,
)


class FailingArchive(Archive):
    """Wraps another Archive and injects ArchiveError on specific method calls.

    Use `fail(method, error, path=None)` to register a failure: the next call
    matching `method` (and optionally `path`) raises `error` instead of
    delegating. Failures are one-shot and consumed on use.
    """

    def __init__(self, inner: Archive) -> None:
        self._inner = inner
        self._failures: list[tuple[str, Path | None, ArchiveError]] = []

    def fail(self, method: str, error: ArchiveError, path: Path | None = None) -> None:
        self._failures.append((method, path, error))

    def _maybe_fail(self, method: str, path: Path | None) -> None:
        for i, (m, p, err) in enumerate(self._failures):
            if m == method and (p is None or p == path):
                del self._failures[i]
                raise err

    @override
    def detect_format(self, path: Path) -> ArchiveFormat | None:
        return self._inner.detect_format(path)

    @override
    def extract(self, src: Path, dest: Path, format: ArchiveFormat) -> None:
        self._maybe_fail("extract", src)
        self._inner.extract(src, dest, format)
