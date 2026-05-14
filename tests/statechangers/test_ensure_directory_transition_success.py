from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def test_transition_creates_directory_under_existing_parent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=Path("/work/data")),
        file_system=fs,
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_dir(Path("/work/data"))


def test_transition_creates_intermediate_parents_when_parents_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=Path("/work/a/b/c"), parents=True),
        file_system=fs,
    )

    assert changer.transition().status is ResultStatus.SUCCESS
    assert fs.is_dir(Path("/work/a"))
    assert fs.is_dir(Path("/work/a/b"))
    assert fs.is_dir(Path("/work/a/b/c"))


def test_transition_applies_mode_after_creation() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/data")
    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=target, mode=0o700),
        file_system=fs,
    )

    assert changer.transition().status is ResultStatus.SUCCESS
    assert fs.stat_mode(target) == 0o700


def test_transition_is_idempotent_when_directory_already_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/data"))
    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=Path("/work/data")),
        file_system=fs,
    )

    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED


def test_transition_applies_mode_when_directory_already_exists_with_wrong_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/data"), mode=0o755)
    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=Path("/work/data"), mode=0o700),
        file_system=fs,
    )

    assert changer.transition().status is ResultStatus.SUCCESS
    assert fs.stat_mode(Path("/work/data")) == 0o700
