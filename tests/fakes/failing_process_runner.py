from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl._interfaces.process import (
    ProcessResult,
    ProcessRunner,
)


class FailingProcessRunner(ProcessRunner):
    """Wraps another ProcessRunner and injects exceptions on specific method
    calls. Use `fail(method, error)` to register a one-shot failure: the next
    matching call raises `error` instead of delegating to the inner runner.
    Mirrors FailingFileSystem.
    """

    def __init__(self, inner: ProcessRunner) -> None:
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
    def which(self, name: str) -> Path | None:
        self._maybe_fail("which")
        return self._inner.which(name)

    @override
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult:
        self._maybe_fail("run")
        return self._inner.run(
            argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout
        )
