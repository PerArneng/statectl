from __future__ import annotations

from pathlib import Path
from typing import Mapping, override

from statectl._interfaces.http import (
    HttpClient,
    HttpResponse,
)


class FailingHttpClient(HttpClient):
    """Wraps another HttpClient and injects exceptions on specific method
    calls. Use `fail(method, error)` to register a one-shot failure: the next
    matching call raises `error` instead of delegating. Mirrors
    FailingProcessRunner / FailingFileSystem.
    """

    def __init__(self, inner: HttpClient) -> None:
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
    def get(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        self._maybe_fail("get")
        return self._inner.get(url, headers=headers, timeout=timeout)

    @override
    def download_to_file(
        self,
        url: str,
        dest: Path,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        self._maybe_fail("download_to_file")
        self._inner.download_to_file(url, dest, headers=headers, timeout=timeout)
