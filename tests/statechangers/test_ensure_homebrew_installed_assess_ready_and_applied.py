from __future__ import annotations

import stat
from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


PREFIX = Path("/opt/homebrew")
BREW_BINARY = PREFIX / "bin" / "brew"


def _build(
    fs: InMemoryFileSystem,
    *,
    accept_eula: bool = True,
) -> EnsureHomebrewInstalledStateChanger:
    return EnsureHomebrewInstalledStateChanger(
        EnsureHomebrewInstalledParameters(
            brew_prefix=PREFIX,
            accept_eula=accept_eula,
        ),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.darwin(),
    )


def _fs_with_prefix() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    fs.add_dir(PREFIX)
    fs.add_dir(PREFIX / "bin")
    return fs


def test_ready_when_brew_absent_and_accept_eula_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))

    assessment = _build(fs).assess_state()

    assert assessment.state is ExistingState.READY


def test_already_applied_when_brew_binary_present_and_executable() -> None:
    fs = _fs_with_prefix()
    fs.add_file(BREW_BINARY, content="#!/bin/bash", mode=0o755)

    assessment = _build(fs).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_brew_binary_present_but_not_executable() -> None:
    """No exec bits → the sentinel is missing, even if the file exists.
    accept_eula must be True to avoid being flagged INVALID for that.
    """
    fs = _fs_with_prefix()
    fs.add_file(BREW_BINARY, content="#!/bin/bash", mode=0o644)

    assessment = _build(fs, accept_eula=True).assess_state()

    assert assessment.state is ExistingState.READY


def test_already_applied_with_only_user_exec_bit() -> None:
    fs = _fs_with_prefix()
    fs.add_file(BREW_BINARY, content="#!/bin/bash", mode=stat.S_IXUSR | 0o600)

    assessment = _build(fs).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_skips_accept_eula_check() -> None:
    """When brew is already installed, accept_eula=False must NOT be flagged
    INVALID — the check only matters for a fresh install.
    """
    fs = _fs_with_prefix()
    fs.add_file(BREW_BINARY, content="#!/bin/bash", mode=0o755)

    assessment = _build(fs, accept_eula=False).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED
