from __future__ import annotations

import shlex
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from statectl._interfaces.clock import Clock
from statectl._interfaces.env import Env
from statectl._interfaces.fs import FileSystem
from statectl._interfaces.http import HttpClient
from statectl._interfaces.process import ProcessRunner
from statectl._statechangers.brew_cask import (
    BrewCaskParameters,
    BrewCaskStateChanger,
)
from statectl._statechangers.fetch_url_to_string import (
    FetchUrlToStringParameters,
    FetchUrlToStringStateChanger,
)
from statectl._statechangers.ensure_homebrew_installed import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from statectl._statechangers.delete_path import (
    DeletePathParameters,
    DeletePathStateChanger,
    PathKind,
)
from statectl._statechangers.ensure_directory import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from statectl._statechangers.ensure_line_in_file import (
    EnsureLineInFileParameters,
    EnsureLineInFileStateChanger,
    Placement,
)
from statectl._statechangers.new_text_file import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from statectl._statechangers.replace_in_file import (
    Match,
    ReplaceInFileParameters,
    ReplaceInFileStateChanger,
)
from statectl._statechangers.run_command import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from statectl._statechangers.set_file_mode import (
    SetFileModeParameters,
    SetFileModeStateChanger,
)


class StateChangers:
    def __init__(
        self,
        file_system: FileSystem,
        process_runner: ProcessRunner,
        http_client: HttpClient,
        env: Env,
        clock: Clock,
    ) -> None:
        self._fs: FileSystem = file_system
        self._pr: ProcessRunner = process_runner
        self._http: HttpClient = http_client
        self._env: Env = env
        self._clock: Clock = clock

    def brew_cask(
        self,
        name: str,
        *,
        version: str | None = None,
        tap: str | None = None,
    ) -> BrewCaskStateChanger:
        return BrewCaskStateChanger(
            BrewCaskParameters(name=name, version=version, tap=tap),
            process_runner=self._pr,
        )

    def ensure_homebrew_installed(
        self,
        brew_prefix: str | Path,
        *,
        install_script_url: str = (
            "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
        ),
        accept_eula: bool = False,
    ) -> EnsureHomebrewInstalledStateChanger:
        return EnsureHomebrewInstalledStateChanger(
            EnsureHomebrewInstalledParameters(
                brew_prefix=Path(brew_prefix),
                install_script_url=install_script_url,
                accept_eula=accept_eula,
            ),
            file_system=self._fs,
            process_runner=self._pr,
            http_client=self._http,
            env=self._env,
        )

    def ensure_directory(
        self,
        path: str | Path,
        *,
        mode: int | None = None,
        parents: bool = True,
    ) -> EnsureDirectoryStateChanger:
        return EnsureDirectoryStateChanger(
            EnsureDirectoryParameters(path=Path(path), mode=mode, parents=parents),
            file_system=self._fs,
        )

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

    def fetch_url_to_string(
        self,
        url: str,
        cache_path: str | Path,
        *,
        max_age: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
        encoding: str = "utf-8",
        timeout: float | None = None,
    ) -> FetchUrlToStringStateChanger:
        return FetchUrlToStringStateChanger(
            FetchUrlToStringParameters(
                url=url,
                cache_path=Path(cache_path),
                max_age=max_age,
                headers=dict(headers) if headers is not None else {},
                encoding=encoding,
                timeout=timeout,
            ),
            file_system=self._fs,
            http_client=self._http,
            clock=self._clock,
        )

    def delete_path(
        self,
        path: str | Path,
        kind: PathKind,
        *,
        recursive: bool = False,
        missing_ok: bool = True,
    ) -> DeletePathStateChanger:
        return DeletePathStateChanger(
            DeletePathParameters(
                path=Path(path),
                kind=kind,
                recursive=recursive,
                missing_ok=missing_ok,
            ),
            file_system=self._fs,
        )

    def ensure_line_in_file(
        self,
        path: str | Path,
        line: str,
        placement: Placement,
        *,
        strict_anchor: bool = True,
        encoding: str = "utf-8",
    ) -> EnsureLineInFileStateChanger:
        return EnsureLineInFileStateChanger(
            EnsureLineInFileParameters(
                path=Path(path),
                line=line,
                placement=placement,
                strict_anchor=strict_anchor,
                encoding=encoding,
            ),
            file_system=self._fs,
        )

    def replace_in_file(
        self,
        path: str | Path,
        match: Match,
        *,
        encoding: str = "utf-8",
    ) -> ReplaceInFileStateChanger:
        return ReplaceInFileStateChanger(
            ReplaceInFileParameters(
                path=Path(path),
                match=match,
                encoding=encoding,
            ),
            file_system=self._fs,
        )

    def set_file_mode(
        self,
        path: str | Path,
        mode: int,
        *,
        follow_symlinks: bool = True,
    ) -> SetFileModeStateChanger:
        return SetFileModeStateChanger(
            SetFileModeParameters(
                path=Path(path),
                mode=mode,
                follow_symlinks=follow_symlinks,
            ),
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
