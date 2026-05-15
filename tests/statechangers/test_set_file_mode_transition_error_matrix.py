from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.fs import (
    FsError,
    FsIoError,
    FsNotFound,
    FsPermissionDenied,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _seed() -> tuple[InMemoryFileSystem, Path]:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    target = Path("/work/x")
    inner.add_file(target, mode=0o600)
    return inner, target


@pytest.mark.parametrize(
    "err",
    [
        FsIoError("io"),
        FsPermissionDenied("denied"),
    ],
)
def test_fs_errors_map_to_chmod_failed(err: FsError) -> None:
    inner, target = _seed()
    fs = FailingFileSystem(inner)
    fs.fail("chmod", err, path=target)

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=target, mode=0o644),
        file_system=fs,
    )
    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHMOD_FAILED"


def test_fs_not_found_during_transition_maps_to_path_vanished() -> None:
    inner, target = _seed()
    fs = FailingFileSystem(inner)
    fs.fail("chmod", FsNotFound("gone", path=target), path=target)

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=target, mode=0o644),
        file_system=fs,
    )
    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "PATH_VANISHED"


def test_path_missing_at_transition_time_returns_path_vanished() -> None:
    # No file at the path — stat_mode returns None
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=Path("/work/missing"), mode=0o644),
        file_system=fs,
    )
    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "PATH_VANISHED"


def test_unexpected_exception_propagates() -> None:
    inner, target = _seed()

    class Exploding(InMemoryFileSystem):
        def chmod(  # pyrefly: ignore
            self, path: Path, mode: int, follow_symlinks: bool = True
        ) -> None:
            raise RuntimeError("kaboom")

    fs = Exploding(_nodes=inner._nodes)

    ch = SetFileModeStateChanger(
        SetFileModeParameters(path=target, mode=0o644),
        file_system=fs,
    )

    with pytest.raises(RuntimeError, match="kaboom"):
        ch.transition()
