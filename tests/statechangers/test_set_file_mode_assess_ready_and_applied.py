from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _assess(
    fs: InMemoryFileSystem, path: Path, mode: int, follow_symlinks: bool = True
) -> object:
    return SetFileModeStateChanger(
        SetFileModeParameters(path=path, mode=mode, follow_symlinks=follow_symlinks),
        file_system=fs,
    ).assess_state()


@pytest.mark.parametrize(
    "kind",
    ["file", "dir"],
)
def test_ready_when_mode_differs(kind: str) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/x")
    if kind == "file":
        fs.add_file(target, mode=0o600)
    else:
        fs.add_dir(target, mode=0o700)

    a = _assess(fs, target, mode=0o644)
    assert a.state is ExistingState.READY


@pytest.mark.parametrize(
    ("kind", "mode"),
    [("file", 0o644), ("file", 0o755), ("dir", 0o755)],
)
def test_already_applied_when_mode_matches(kind: str, mode: int) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/x")
    if kind == "file":
        fs.add_file(target, mode=mode)
    else:
        fs.add_dir(target, mode=mode)

    a = _assess(fs, target, mode=mode)
    assert a.state is ExistingState.ALREADY_APPLIED


def test_symlink_follow_true_compares_target_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/lnk"), mode=0o644, link_mode=0o777)

    assert _assess(fs, Path("/work/lnk"), mode=0o644, follow_symlinks=True).state is (
        ExistingState.ALREADY_APPLIED
    )
    assert _assess(fs, Path("/work/lnk"), mode=0o600, follow_symlinks=True).state is (
        ExistingState.READY
    )


def test_symlink_follow_false_compares_link_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/lnk"), mode=0o644, link_mode=0o777)

    assert _assess(fs, Path("/work/lnk"), mode=0o777, follow_symlinks=False).state is (
        ExistingState.ALREADY_APPLIED
    )
    assert _assess(fs, Path("/work/lnk"), mode=0o700, follow_symlinks=False).state is (
        ExistingState.READY
    )
