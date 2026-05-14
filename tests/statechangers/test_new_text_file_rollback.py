from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import (
    FsIoError,
    FsNotFound,
)
from statectl._state_changer import ExistingState, ResultStatus, RollbackableStateChanger
from statectl._statechangers import (
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


def test_rollback_returns_a_state_changer_not_rollbackable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    assert not hasattr(rollback, "rollback")


def test_rollback_assess_already_applied_when_file_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    assessment = rollback.assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_rollback_assess_ready_when_file_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/hello.txt"), content="hi")
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    assessment = rollback.assess_state()

    assert assessment.state is ExistingState.READY


def test_rollback_assess_invalid_when_path_is_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/hello.txt"))
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    assessment = rollback.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("non-file" in i for i in assessment.issues)


def test_rollback_assess_invalid_when_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_file(Path("/work/hello.txt"), content="hi", writable=True)
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    assessment = rollback.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_rollback_assess_collects_all_issues() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_dir(Path("/work/hello.txt"))
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    assessment = rollback.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert len(assessment.issues) == 2


def test_rollback_transition_removes_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/hello.txt"), content="hi")
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    result = rollback.transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(Path("/work/hello.txt"))


def test_rollback_transition_skipped_when_file_disappeared() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(Path("/work/hello.txt"), content="hi")
    fs = FailingFileSystem(inner)
    fs.fail(
        "delete_file",
        FsNotFound("path not found", path=Path("/work/hello.txt")),
        path=Path("/work/hello.txt"),
    )
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    result = rollback.transition()

    assert result.status is ResultStatus.SKIPPED


def test_rollback_transition_failure_on_other_fs_error() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(Path("/work/hello.txt"), content="hi")
    fs = FailingFileSystem(inner)
    fs.fail(
        "delete_file",
        FsIoError("device busy", path=Path("/work/hello.txt")),
        path=Path("/work/hello.txt"),
    )
    rollback = _changer(fs, Path("/work/hello.txt"), "hi").rollback()

    result = rollback.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "UNLINK_FAILED"
    assert "device busy" in (result.message or "")
