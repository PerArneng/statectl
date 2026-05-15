from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import DeletePathParameters, DeletePathStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem


@pytest.mark.parametrize(
    "kind",
    ["file", "symlink", "dir", "any"],
)
def test_missing_path_already_applied_when_missing_ok(kind: str) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/gone"), kind=kind, missing_ok=True),  # type: ignore[arg-type]
        file_system=fs,
    )
    a = ch.assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED


def test_ready_for_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/f"), kind="file"),
        file_system=fs,
    )
    assert ch.assess_state().state is ExistingState.READY


def test_ready_for_symlink() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"))
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/link"), kind="symlink"),
        file_system=fs,
    )
    assert ch.assess_state().state is ExistingState.READY


def test_ready_for_empty_dir_without_recursive() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/d"), kind="dir", recursive=False),
        file_system=fs,
    )
    assert ch.assess_state().state is ExistingState.READY


def test_ready_for_nonempty_dir_with_recursive() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))
    fs.add_file(Path("/work/d/child"))
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/d"), kind="dir", recursive=True),
        file_system=fs,
    )
    assert ch.assess_state().state is ExistingState.READY


def test_ready_for_any_kind_matches_actual_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))
    ch = DeletePathStateChanger(
        DeletePathParameters(path=Path("/work/f"), kind="any"),
        file_system=fs,
    )
    assert ch.assess_state().state is ExistingState.READY
