from __future__ import annotations

import shlex
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from statectl._interfaces.fs import FileSystem
from statectl._interfaces.process import ProcessRunner
from statectl._statechangers.new_text_file import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from statectl._statechangers.run_command import (
    RunCommandParameters,
    RunCommandStateChanger,
)


class StateChangers:
    def __init__(
        self,
        file_system: FileSystem,
        process_runner: ProcessRunner,
    ) -> None:
        self._fs: FileSystem = file_system
        self._pr: ProcessRunner = process_runner

    def new_file(
        self,
        path: str | Path,
        text: str,
        encoding: str = "utf-8",
    ) -> NewTextFileStateChanger:
        return NewTextFileStateChanger(
            NewTextFileParameters(path=Path(path), text=text, encoding=encoding),
            file_system=self._fs,
        )

    def run(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        creates: str | Path | None = None,
        removes: str | Path | None = None,
        expected_exit_codes: Iterable[int] = (0,),
        timeout: float | None = None,
    ) -> RunCommandStateChanger:
        argv: tuple[str, ...] = (
            tuple(shlex.split(command)) if isinstance(command, str) else tuple(command)
        )
        return RunCommandStateChanger(
            RunCommandParameters(
                argv=argv,
                cwd=Path(cwd) if cwd is not None else None,
                env=env,
                creates=Path(creates) if creates is not None else None,
                removes=Path(removes) if removes is not None else None,
                expected_exit_codes=frozenset(expected_exit_codes),
                timeout=timeout,
            ),
            process_runner=self._pr,
            file_system=self._fs,
        )
