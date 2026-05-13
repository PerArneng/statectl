from __future__ import annotations

from pathlib import Path

from statectl.interfaces.fs.error.fs_io_error import FsIoError
from statectl.state_changer import ResultStatus, RollbackableStateChanger
from statectl.statechangers.new_text_file import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem | FailingFileSystem, path: Path, text: str) -> RollbackableStateChanger:
    return NewTextFileStateChanger(
        NewTextFileParameters(path=path, text=text),
        file_system=fs,
    )


def test_transition_writes_file_and_returns_success() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, Path("/work/hello.txt"), "hi there")

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_file(Path("/work/hello.txt"))
    assert fs.read_text_file(Path("/work/hello.txt")) == "hi there"


def test_transition_returns_failure_when_write_raises_fs_error() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)
    fs.fail(
        "write_text_file",
        FsIoError("disk full", path=Path("/work/hello.txt")),
        path=Path("/work/hello.txt"),
    )
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"
    assert "disk full" in (result.message or "")
    assert not inner.exists(Path("/work/hello.txt"))


def test_transition_failure_does_not_leak_stdlib_exception() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"), writable=False)
    fs = inner
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"
