from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(
    fs: InMemoryFileSystem,
    path: Path,
    *,
    mode: int | None = None,
    parents: bool = True,
) -> EnsureDirectoryStateChanger:
    return EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=path, mode=mode, parents=parents),
        file_system=fs,
    )


def test_ready_when_path_missing_and_parent_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs, Path("/work/data")).assess_state()

    assert assessment.state is ExistingState.READY
    assert assessment.issues == []


def test_ready_when_path_missing_and_only_some_ancestor_exists_with_parents_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs, Path("/work/a/b/c"), parents=True).assess_state()

    assert assessment.state is ExistingState.READY


def test_already_applied_when_directory_exists_and_no_mode_requested() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/data"))

    assessment = _changer(fs, Path("/work/data")).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_directory_exists_with_matching_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/data"), mode=0o750)

    assessment = _changer(fs, Path("/work/data"), mode=0o750).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_directory_exists_but_mode_differs() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/data"), mode=0o755)

    assessment = _changer(fs, Path("/work/data"), mode=0o700).assess_state()

    assert assessment.state is ExistingState.READY


@pytest.mark.parametrize(
    "mode", [0o000, 0o755, 0o7777], ids=["min", "common", "max"]
)
def test_valid_mode_boundaries_are_accepted(mode: int) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs, Path("/work/data"), mode=mode).assess_state()

    assert assessment.state is ExistingState.READY
