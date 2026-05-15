from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import DeletePathParameters, DeletePathStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _assess(fs: InMemoryFileSystem, params: DeletePathParameters) -> object:
    return DeletePathStateChanger(params, file_system=fs).assess_state()


def test_missing_path_invalid_when_missing_ok_false() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    a = _assess(
        fs,
        DeletePathParameters(path=Path("/work/gone"), kind="file", missing_ok=False),
    )
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    assert any("does not exist" in i for i in a.issues)  # type: ignore[attr-defined]


def test_kind_mismatch_file_vs_dir() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))
    a = _assess(fs, DeletePathParameters(path=Path("/work/d"), kind="file"))
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    assert any("expected file" in i and "is dir" in i for i in a.issues)  # type: ignore[attr-defined]


def test_kind_mismatch_dir_vs_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))
    a = _assess(fs, DeletePathParameters(path=Path("/work/f"), kind="dir"))
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    assert any("expected dir" in i for i in a.issues)  # type: ignore[attr-defined]


def test_kind_symlink_against_regular_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))
    a = _assess(fs, DeletePathParameters(path=Path("/work/f"), kind="symlink"))
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    assert any("expected symlink" in i for i in a.issues)  # type: ignore[attr-defined]


def test_nonempty_dir_without_recursive() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))
    fs.add_file(Path("/work/d/child"))
    a = _assess(fs, DeletePathParameters(path=Path("/work/d"), kind="dir", recursive=False))
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    assert any("directory not empty" in i for i in a.issues)  # type: ignore[attr-defined]


def test_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_file(Path("/work/f"), writable=False)
    a = _assess(fs, DeletePathParameters(path=Path("/work/f"), kind="file"))
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    assert any("parent not writable" in i for i in a.issues)  # type: ignore[attr-defined]


def test_collects_multiple_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_dir(Path("/work/d"), writable=True)
    fs.add_file(Path("/work/d/child"))
    a = _assess(fs, DeletePathParameters(path=Path("/work/d"), kind="file", recursive=False))
    assert a.state is ExistingState.INVALID  # type: ignore[attr-defined]
    # expects: kind mismatch + parent not writable (non-empty dir would also fire if kind=dir)
    joined = " | ".join(a.issues)  # type: ignore[attr-defined]
    assert "expected file" in joined
    assert "parent not writable" in joined
