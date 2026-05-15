from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _make(
    fs: InMemoryFileSystem,
    *,
    overwrite_non_symlink: bool = False,
    allow_dangling: bool = True,
) -> EnsureSymlinkStateChanger:
    return EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(
            link_path=Path("/work/link"),
            target=Path("/work/target"),
            overwrite_non_symlink=overwrite_non_symlink,
            allow_dangling=allow_dangling,
        ),
        file_system=fs,
    )


def test_ready_when_link_absent_target_present() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/target"), content="hi")
    assert _make(fs).assess_state().state is ExistingState.READY


def test_ready_when_link_absent_target_missing_dangling_allowed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    assert _make(fs, allow_dangling=True).assess_state().state is ExistingState.READY


def test_already_applied_when_link_points_at_target() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"), target=Path("/work/target"))
    assert _make(fs).assess_state().state is ExistingState.ALREADY_APPLIED


def test_ready_when_symlink_points_at_different_target() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_symlink(Path("/work/link"), target=Path("/work/other"))
    # different target → READY (relinking is safe)
    assert _make(fs).assess_state().state is ExistingState.READY


def test_ready_when_regular_file_with_overwrite_enabled() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/link"), content="old")
    assert _make(fs, overwrite_non_symlink=True).assess_state().state is ExistingState.READY


def test_already_applied_byte_exact_target_match_no_resolution() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    # relative target stored byte-exact
    fs.add_symlink(Path("/work/link"), target=Path("target"))
    changer = EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(
            link_path=Path("/work/link"),
            target=Path("target"),  # same bytes
        ),
        file_system=fs,
    )
    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED
