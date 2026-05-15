from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ResultStatus
from statectl._statechangers import DeletePathParameters, DeletePathStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _run(fs: InMemoryFileSystem, params: DeletePathParameters) -> object:
    return DeletePathStateChanger(params, file_system=fs).transition()


def test_delete_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))
    r = _run(fs, DeletePathParameters(path=Path("/work/f"), kind="file"))
    assert r.status is ResultStatus.SUCCESS  # type: ignore[attr-defined]
    assert not fs.exists(Path("/work/f"))


def test_delete_symlink() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"))
    r = _run(fs, DeletePathParameters(path=Path("/work/link"), kind="symlink"))
    assert r.status is ResultStatus.SUCCESS  # type: ignore[attr-defined]
    assert not fs.exists(Path("/work/link"))


def test_delete_empty_dir() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))
    r = _run(fs, DeletePathParameters(path=Path("/work/d"), kind="dir"))
    assert r.status is ResultStatus.SUCCESS  # type: ignore[attr-defined]
    assert not fs.exists(Path("/work/d"))


def test_delete_nonempty_dir_recursive() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))
    fs.add_file(Path("/work/d/child"))
    r = _run(fs, DeletePathParameters(path=Path("/work/d"), kind="dir", recursive=True))
    assert r.status is ResultStatus.SUCCESS  # type: ignore[attr-defined]
    assert not fs.exists(Path("/work/d"))
    assert not fs.exists(Path("/work/d/child"))


def test_delete_any_dispatches_to_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))
    r = _run(fs, DeletePathParameters(path=Path("/work/f"), kind="any"))
    assert r.status is ResultStatus.SUCCESS  # type: ignore[attr-defined]
    assert not fs.exists(Path("/work/f"))


def test_transition_skipped_when_path_vanishes_between_assess_and_transition() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    # Simulate vanish: nothing exists at transition time
    r = _run(fs, DeletePathParameters(path=Path("/work/gone"), kind="file"))
    assert r.status is ResultStatus.SKIPPED  # type: ignore[attr-defined]
