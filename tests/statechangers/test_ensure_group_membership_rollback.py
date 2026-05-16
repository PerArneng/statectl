from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipRollbackStateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _params() -> EnsureGroupMembershipParameters:
    return EnsureGroupMembershipParameters(user="alice", group="docker")


def test_rollback_already_applied_when_user_not_member() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("gpasswd")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0, stdout="alice users\n", stderr="", duration_ms=0
        ),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(), process_runner=pr, env=ScriptedEnv.linux()
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_user_is_member() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("gpasswd")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice users docker\n",
            stderr="",
            duration_ms=0,
        ),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(), process_runner=pr, env=ScriptedEnv.linux()
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.READY


def test_rollback_invalid_when_gpasswd_missing() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice users docker\n",
            stderr="",
            duration_ms=0,
        ),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(), process_runner=pr, env=ScriptedEnv.linux()
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("gpasswd not on PATH" in i for i in assess.issues)


def test_rollback_invalid_when_user_missing() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("gpasswd")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(), process_runner=pr, env=ScriptedEnv.linux()
    )

    assess = inverse.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("user not found" in i for i in assess.issues)


def test_rollback_transition_runs_gpasswd_on_linux() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("gpasswd")
    pr.register(
        ("gpasswd", "-d", "alice", "docker"),
        ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=1),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(), process_runner=pr, env=ScriptedEnv.linux()
    )

    result = inverse.transition()

    assert result.status is ResultStatus.SUCCESS
    assert ("gpasswd", "-d", "alice", "docker") in [c.argv for c in pr.calls]


def test_rollback_transition_runs_dseditgroup_on_darwin() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("dseditgroup")
    pr.register(
        ("dseditgroup", "-o", "edit", "-d", "alice", "-t", "user", "wheel"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="wheel"),
        process_runner=pr,
        env=ScriptedEnv.darwin(),
    )

    result = inverse.transition()

    assert result.status is ResultStatus.SUCCESS
    assert (
        "dseditgroup",
        "-o",
        "edit",
        "-d",
        "alice",
        "-t",
        "user",
        "wheel",
    ) in [c.argv for c in pr.calls]


def test_rollback_transition_fails_with_membership_remove_failed_on_nonzero() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("gpasswd")
    pr.register(
        ("gpasswd", "-d", "alice", "docker"),
        ProcessResult(
            exit_code=3, stdout="", stderr="not a member", duration_ms=1
        ),
    )
    inverse = EnsureGroupMembershipRollbackStateChanger(
        _params(), process_runner=pr, env=ScriptedEnv.linux()
    )

    result = inverse.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "MEMBERSHIP_REMOVE_FAILED"
    assert result.details["exit_code"] == "3"
