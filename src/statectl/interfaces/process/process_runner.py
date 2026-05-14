from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class ProcessRunner(ABC):
    """Process execution abstraction. The query method `which` never raises;
    the action method `run` raises ProcessError subclasses on launch problems
    but returns a ProcessResult for any exit code (zero or non-zero) so that
    callers own exit-code policy.

    Implementations must translate underlying errors into:
      - ProcessNotFound       executable could not be found at launch
      - ProcessTimeout        the process did not complete within `timeout`
      - ProcessLaunchError    OS-level launch failure (permissions, ENOEXEC, ...)
      - ProcessDecodeError    stdout/stderr bytes could not be decoded as text
    """

    @abstractmethod
    def which(self, name: str) -> Path | None: ...

    @abstractmethod
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult: ...
