from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    CopyFileParameters,
    CopyFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


SRC = Path("/work/a")
DEST = Path("/work/b")


def _changer(fs: InMemoryFileSystem, **overrides: object) -> CopyFileStateChanger:
    kwargs: dict[str, object] = {"src": SRC, "dest": DEST}
    kwargs.update(overrides)
    return CopyFileStateChanger(
        CopyFileParameters(**kwargs),  # pyrefly: ignore
        file_system=fs,
    )


def test_ready_when_dest_absent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.READY


def test_already_applied_when_dest_matches_src_and_no_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    fs.add_file(DEST, content="hello\n")

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_dest_matches_and_mode_matches() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    fs.add_file(DEST, content="hello\n", mode=0o600)

    a = _changer(fs, mode=0o600).assess_state()

    assert a.state is ExistingState.ALREADY_APPLIED


def test_ready_when_content_matches_but_mode_differs() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    fs.add_file(DEST, content="hello\n", mode=0o644)

    a = _changer(fs, mode=0o600).assess_state()

    assert a.state is ExistingState.READY


def test_ready_when_dest_differs_but_overwrite_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    fs.add_file(DEST, content="other\n")

    a = _changer(fs, overwrite=True).assess_state()

    assert a.state is ExistingState.READY
