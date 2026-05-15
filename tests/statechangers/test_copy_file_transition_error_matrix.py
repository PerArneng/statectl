from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError, FsNotFound, FsPermissionDenied
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    CopyFileParameters,
    CopyFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


SRC = Path("/work/a")
DEST = Path("/work/b")


def _setup() -> tuple[InMemoryFileSystem, FailingFileSystem]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(SRC, content="hello\n")
    return inner, FailingFileSystem(inner)


def _changer(fs: FailingFileSystem, **overrides: object) -> CopyFileStateChanger:
    kwargs: dict[str, object] = {"src": SRC, "dest": DEST}
    kwargs.update(overrides)
    return CopyFileStateChanger(
        CopyFileParameters(**kwargs),  # pyrefly: ignore
        file_system=fs,
    )


def test_copy_failure_io_maps_to_write_failed() -> None:
    inner, fs = _setup()
    fs.fail("copy_file", FsIoError("disk full", path=DEST), path=SRC)

    result = _changer(fs).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


def test_copy_failure_permission_maps_to_write_failed() -> None:
    inner, fs = _setup()
    fs.fail("copy_file", FsPermissionDenied("nope", path=DEST), path=SRC)

    result = _changer(fs).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


def test_src_vanished_maps_to_src_vanished() -> None:
    inner, fs = _setup()
    fs.fail("copy_file", FsNotFound("gone", path=SRC), path=SRC)

    result = _changer(fs).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "SRC_VANISHED"


def test_chmod_failure_after_copy_maps_to_chmod_failed() -> None:
    inner, fs = _setup()
    fs.fail("chmod", FsPermissionDenied("nope", path=DEST), path=DEST)

    result = _changer(fs, mode=0o600).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHMOD_FAILED"


def test_pre_image_read_failure_maps_to_read_failed() -> None:
    inner, fs = _setup()
    inner.add_file(DEST, content="other\n")
    fs.fail("read_binary_file", FsIoError("io", path=DEST), path=DEST)

    result = _changer(fs, overwrite=True).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "READ_FAILED"


def test_unexpected_exception_propagates() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(SRC, content="hello\n")

    class _Boom(InMemoryFileSystem):
        def copy_file(self, src: Path, dest: Path, preserve_mtime: bool = False) -> None:
            raise RuntimeError("kaboom")

    boom = _Boom()
    boom.add_dir(Path("/work"))
    boom.add_file(SRC, content="hello\n")

    ch = CopyFileStateChanger(
        CopyFileParameters(src=SRC, dest=DEST),
        file_system=boom,
    )
    try:
        ch.transition()
    except RuntimeError as e:
        assert "kaboom" in str(e)
    else:
        raise AssertionError("expected RuntimeError to propagate")
