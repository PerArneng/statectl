from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _assess(fs: InMemoryFileSystem, **kwargs: object) -> object:
    params = SetFileModeParameters(
        path=kwargs.pop("path", Path("/work/x")),  # type: ignore[arg-type]
        mode=kwargs.pop("mode", 0o644),  # type: ignore[arg-type]
        follow_symlinks=kwargs.pop("follow_symlinks", True),  # type: ignore[arg-type]
    )
    return SetFileModeStateChanger(params, file_system=fs).assess_state()


def test_invalid_when_path_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    a = _assess(fs)
    assert a.state is ExistingState.INVALID
    assert any("does not exist" in i for i in a.issues)


def test_invalid_when_mode_out_of_range_high() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o644)

    a = _assess(fs, mode=0o10000)
    assert a.state is ExistingState.INVALID
    assert any("out of range" in i for i in a.issues)


def test_invalid_when_mode_out_of_range_negative() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o644)

    a = _assess(fs, mode=-1)
    assert a.state is ExistingState.INVALID
    assert any("out of range" in i for i in a.issues)


def test_invalid_when_follow_symlinks_false_and_lchmod_unsupported() -> None:
    fs = InMemoryFileSystem()
    fs.lchmod_supported = False
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/x"), link_mode=0o777)

    a = _assess(fs, follow_symlinks=False, mode=0o600)
    assert a.state is ExistingState.INVALID
    assert any("lchmod unsupported" in i for i in a.issues)


def test_collects_multiple_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.lchmod_supported = False
    fs.add_dir(Path("/work"))
    # path missing AND mode out of range AND lchmod unsupported

    a = _assess(fs, mode=0o10000, follow_symlinks=False)
    assert a.state is ExistingState.INVALID
    assert len(a.issues) == 3
