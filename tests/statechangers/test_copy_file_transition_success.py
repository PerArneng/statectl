from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ResultStatus
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


def test_transition_creates_dest_when_absent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    ch = _changer(fs)

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(DEST) == "hello\n"
    assert result.details["dest_existed"] == "False"


def test_transition_overwrites_when_overwrite_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    fs.add_file(DEST, content="other\n")
    ch = _changer(fs, overwrite=True)

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(DEST) == "hello\n"
    assert result.details["dest_existed"] == "True"


def test_transition_applies_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    ch = _changer(fs, mode=0o600)

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.stat_mode(DEST) == 0o600


def test_idempotent_after_first_transition() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    ch = _changer(fs)

    ch.transition()
    second = _changer(fs).assess_state()

    from statectl._state_changer import ExistingState

    assert second.state is ExistingState.ALREADY_APPLIED
