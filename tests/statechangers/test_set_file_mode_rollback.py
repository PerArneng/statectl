from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError, FsNotFound
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeRollbackStateChanger,
    SetFileModeStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


TARGET = Path("/work/x")


def _forward(fs: InMemoryFileSystem | FailingFileSystem) -> SetFileModeStateChanger:
    return SetFileModeStateChanger(
        SetFileModeParameters(path=TARGET, mode=0o644),
        file_system=fs,
    )


def test_rollback_carries_pre_mode_from_forward_assess_time() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, mode=0o600)

    forward = _forward(fs)
    rollback = forward.rollback()
    assert isinstance(rollback, SetFileModeRollbackStateChanger)
    assert rollback.pre_mode == 0o600


def test_rollback_already_applied_when_path_absent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, mode=0o600)
    rb = _forward(fs).rollback()

    fs.delete_file(TARGET)

    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_already_applied_when_mode_already_restored() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, mode=0o600)
    rb = _forward(fs).rollback()  # pre_mode captured = 0o600

    # someone else already put it back
    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_after_forward_transition() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, mode=0o600)
    forward = _forward(fs)
    rb = forward.rollback()
    forward.transition()  # mode now 0o644

    assert rb.assess_state().state is ExistingState.READY


def test_rollback_invalid_when_no_pre_mode_captured() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, mode=0o600)

    # construct rollback directly with pre_mode=None
    rb = SetFileModeRollbackStateChanger(
        SetFileModeParameters(path=TARGET, mode=0o644),
        pre_mode=None,
        file_system=fs,
    )

    a = rb.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("no pre-mode captured" in i for i in a.issues)


def test_rollback_transition_restores_pre_mode() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(TARGET, mode=0o600)
    forward = _forward(fs)
    rb = forward.rollback()
    forward.transition()
    assert fs.stat_mode(TARGET) == 0o644

    result = rb.transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.stat_mode(TARGET) == 0o600


def test_rollback_transition_skipped_when_path_vanished() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(TARGET, mode=0o600)
    fs = FailingFileSystem(inner)
    forward = _forward(fs)
    rb = forward.rollback()
    fs.fail("chmod", FsNotFound("gone", path=TARGET), path=TARGET)

    result = rb.transition()

    assert result.status is ResultStatus.SKIPPED


def test_rollback_transition_failure_maps_to_chmod_failed() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    inner.add_file(TARGET, mode=0o600)
    fs = FailingFileSystem(inner)
    forward = _forward(fs)
    rb = forward.rollback()
    fs.fail("chmod", FsIoError("busy", path=TARGET), path=TARGET)

    result = rb.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "CHMOD_FAILED"
