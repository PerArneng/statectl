from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence, override

from statectl.interfaces.process import (
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
)


@dataclass(frozen=True)
class RecordedCall:
    argv: tuple[str, ...]
    cwd: Path | None
    env: Mapping[str, str] | None
    stdin: str | None
    timeout: float | None


@dataclass
class ScriptedProcessRunner(ProcessRunner):
    """In-memory ProcessRunner. Register executables to make `which` succeed,
    and register scripted results matched by argv prefix to drive `run`.

    Unregistered executables: `run` raises ProcessNotFound, `which` returns
    None. Every `run` call is recorded on `.calls` for assertions.
    """

    _executables: dict[str, Path] = field(default_factory=dict)
    _scripts: list[tuple[tuple[str, ...], ProcessResult]] = field(default_factory=list)
    calls: list[RecordedCall] = field(default_factory=list)

    def register_executable(self, name: str, path: Path | None = None) -> None:
        self._executables[name] = path or Path(f"/usr/bin/{name}")

    def unregister_executable(self, name: str) -> None:
        self._executables.pop(name, None)

    def register(self, argv_prefix: Sequence[str], result: ProcessResult) -> None:
        self._scripts.append((tuple(argv_prefix), result))

    @override
    def which(self, name: str) -> Path | None:
        return self._executables.get(name)

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
        argv_tuple = tuple(argv)
        self.calls.append(
            RecordedCall(argv=argv_tuple, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
        )
        if not argv_tuple or argv_tuple[0] not in self._executables:
            raise ProcessNotFound(
                f"executable not found: {argv_tuple[0] if argv_tuple else '<empty>'}",
                argv=argv_tuple,
            )
        for prefix, result in self._scripts:
            if argv_tuple[: len(prefix)] == prefix:
                return result
        return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
