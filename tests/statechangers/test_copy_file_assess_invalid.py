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


def test_invalid_when_src_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("src does not exist" in i for i in a.issues)


def test_invalid_when_src_is_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(SRC)

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("src is not a regular file" in i for i in a.issues)


def test_invalid_when_dest_parent_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="x")
    ch = CopyFileStateChanger(
        CopyFileParameters(src=SRC, dest=Path("/missing/b")),
        file_system=fs,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("dest parent directory does not exist" in i for i in a.issues)


def test_invalid_when_dest_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_file(SRC, content="x", writable=True)

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("dest parent directory is not writable" in i for i in a.issues)


def test_invalid_when_dest_exists_with_different_content_and_no_overwrite() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hello\n")
    fs.add_file(DEST, content="other\n")

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("dest exists with different content" in i for i in a.issues)


def test_invalid_when_dest_is_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="x")
    fs.add_dir(DEST)

    a = _changer(fs).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("dest exists and is not a regular file" in i for i in a.issues)


def test_invalid_when_mode_out_of_range() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="x")

    a = _changer(fs, mode=0o10000).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("mode out of range" in i for i in a.issues)


def test_assess_collects_all_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    # src missing, mode out of range
    a = _changer(fs, mode=0o10000).assess_state()

    assert a.state is ExistingState.INVALID
    assert any("src does not exist" in i for i in a.issues)
    assert any("mode out of range" in i for i in a.issues)
