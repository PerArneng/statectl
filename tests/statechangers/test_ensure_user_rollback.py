from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureUserParameters,
    EnsureUserRollbackStateChanger,
)
from statectl._statechangers.ensure_user import _UserInfo
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._ensure_user_helpers import (
    linux_runner_with_executables,
    register_linux_user,
    register_linux_user_missing,
)


def _rollback(
    pr: ScriptedProcessRunner,
    *,
    created_by_us: bool,
    recorded: _UserInfo | None,
) -> EnsureUserRollbackStateChanger:
    return EnsureUserRollbackStateChanger(
        EnsureUserParameters(username="alice"),
        created_by_us=created_by_us,
        recorded_info=recorded,
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )


def _info(uid: int = 1500, home: str = "/home/alice") -> _UserInfo:
    return _UserInfo(
        uid=uid, home=Path(home), shell=Path("/bin/bash"), primary_gid=uid
    )


def test_already_applied_when_user_absent() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    assess = _rollback(pr, created_by_us=True, recorded=_info()).assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_user_not_created_by_us() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500)
    assess = _rollback(pr, created_by_us=False, recorded=None).assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED


def test_invalid_when_uid_drifted() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=9999, home="/home/alice")
    assess = _rollback(pr, created_by_us=True, recorded=_info(uid=1500)).assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("uid changed" in i for i in assess.issues)


def test_invalid_when_home_drifted() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500, home="/home/elsewhere")
    assess = _rollback(pr, created_by_us=True, recorded=_info()).assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("home changed" in i for i in assess.issues)


def test_ready_when_created_by_us_and_attrs_match() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500, home="/home/alice")
    assess = _rollback(pr, created_by_us=True, recorded=_info()).assess_state()
    assert assess.state is ExistingState.READY


def test_transition_deletes_user_via_userdel() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500, home="/home/alice")
    result = _rollback(
        pr, created_by_us=True, recorded=_info()
    ).transition()
    assert result.status is ResultStatus.SUCCESS
    assert any(c.argv == ("userdel", "alice") for c in pr.calls)


def test_transition_skipped_when_not_created_by_us() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500)
    result = _rollback(pr, created_by_us=False, recorded=None).transition()
    assert result.status is ResultStatus.SKIPPED
    assert not any(c.argv[:1] == ("userdel",) for c in pr.calls)


def test_transition_skipped_when_user_already_gone() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    result = _rollback(pr, created_by_us=True, recorded=_info()).transition()
    assert result.status is ResultStatus.SKIPPED


def test_userdel_failure_maps_to_user_delete_failed() -> None:
    from statectl._interfaces.process import ProcessResult

    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500, home="/home/alice")
    pr.register(
        ("userdel",),
        ProcessResult(exit_code=8, stdout="", stderr="cannot remove\n", duration_ms=0),
    )
    result = _rollback(pr, created_by_us=True, recorded=_info()).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "USER_DELETE_FAILED"
