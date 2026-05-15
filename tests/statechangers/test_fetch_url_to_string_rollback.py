from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError, FsNotFound
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    FetchUrlToStringParameters,
    FetchUrlToStringStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_http_client import ScriptedHttpClient


CACHE = Path("/work/x.txt")


def _changer(fs: InMemoryFileSystem | FailingFileSystem) -> FetchUrlToStringStateChanger:
    return FetchUrlToStringStateChanger(
        FetchUrlToStringParameters(url="https://example.com/x", cache_path=CACHE),
        file_system=fs,
        http_client=ScriptedHttpClient(),
        clock=ScriptedClock(),
    )


def test_rollback_returns_plain_state_changer() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    rollback = _changer(fs).rollback()

    assert not hasattr(rollback, "rollback")


def test_rollback_already_applied_when_cache_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    assessment = _changer(fs).rollback().assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_cache_exists() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(CACHE, content="cached")

    assessment = _changer(fs).rollback().assess_state()

    assert assessment.state is ExistingState.READY


def test_rollback_invalid_when_cache_is_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(CACHE)

    assessment = _changer(fs).rollback().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("non-file" in i for i in assessment.issues)


def test_rollback_invalid_when_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    fs.add_file(CACHE, content="cached", writable=True)

    assessment = _changer(fs).rollback().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_rollback_transition_removes_cache_file() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(CACHE, content="cached")

    result = _changer(fs).rollback().transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(CACHE)


def test_rollback_transition_skipped_when_file_disappeared() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(CACHE, content="cached")
    fs = FailingFileSystem(inner)
    fs.fail("delete_file", FsNotFound("gone", path=CACHE), path=CACHE)

    result = _changer(fs).rollback().transition()

    assert result.status is ResultStatus.SKIPPED


def test_rollback_transition_failure_on_other_fs_error() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(CACHE, content="cached")
    fs = FailingFileSystem(inner)
    fs.fail("delete_file", FsIoError("busy", path=CACHE), path=CACHE)

    result = _changer(fs).rollback().transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "UNLINK_FAILED"
