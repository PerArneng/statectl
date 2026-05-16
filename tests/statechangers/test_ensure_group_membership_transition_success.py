from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipStateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _linux_rig(
    *, group_exists: bool = True, create_group_if_missing: bool = False
) -> tuple[EnsureGroupMembershipStateChanger, ScriptedProcessRunner]:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("getent")
    pr.register_executable("usermod")
    pr.register_executable("groupadd")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0, stdout="alice users\n", stderr="", duration_ms=0
        ),
    )
    pr.register(
        ("getent", "group", "docker"),
        ProcessResult(
            exit_code=0 if group_exists else 2,
            stdout="docker:x:999:\n" if group_exists else "",
            stderr="",
            duration_ms=0,
        ),
    )
    pr.register(
        ("groupadd", "docker"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("usermod", "-aG", "docker", "alice"),
        ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=2),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(
            user="alice",
            group="docker",
            create_group_if_missing=create_group_if_missing,
        ),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )
    return changer, pr


def test_transition_runs_usermod_on_linux() -> None:
    changer, pr = _linux_rig()

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert ("usermod", "-aG", "docker", "alice") in [c.argv for c in pr.calls]
    # Did NOT run groupadd because the group already exists.
    assert not any(c.argv[:1] == ("groupadd",) for c in pr.calls)


def test_transition_creates_group_then_adds_member_when_allowed() -> None:
    changer, pr = _linux_rig(
        group_exists=False, create_group_if_missing=True
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert ("groupadd", "docker") in argvs
    assert ("usermod", "-aG", "docker", "alice") in argvs


def test_transition_fails_with_group_create_failed_when_group_missing_and_create_false() -> None:
    changer, _ = _linux_rig(
        group_exists=False, create_group_if_missing=False
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "GROUP_CREATE_FAILED"


def test_transition_runs_dseditgroup_on_darwin() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("dseditgroup")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice staff\n",
            stderr="",
            duration_ms=0,
        ),
    )
    pr.register(
        ("dseditgroup", "-o", "read", "wheel"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("dseditgroup", "-o", "edit", "-a", "alice", "-t", "user", "wheel"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="wheel"),
        process_runner=pr,
        env=ScriptedEnv.darwin(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert (
        "dseditgroup",
        "-o",
        "edit",
        "-a",
        "alice",
        "-t",
        "user",
        "wheel",
    ) in [c.argv for c in pr.calls]


def test_transition_fails_with_membership_add_failed_on_nonzero_exit() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("getent")
    pr.register_executable("usermod")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0, stdout="alice users\n", stderr="", duration_ms=0
        ),
    )
    pr.register(
        ("getent", "group", "docker"),
        ProcessResult(
            exit_code=0, stdout="docker:x:999:\n", stderr="", duration_ms=0
        ),
    )
    pr.register(
        ("usermod", "-aG", "docker", "alice"),
        ProcessResult(
            exit_code=4, stdout="", stderr="bad arg", duration_ms=1
        ),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="docker"),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "MEMBERSHIP_ADD_FAILED"
    assert result.details["exit_code"] == "4"


def test_transition_fails_with_group_create_failed_on_groupadd_failure() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("getent")
    pr.register_executable("usermod")
    pr.register_executable("groupadd")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0, stdout="alice users\n", stderr="", duration_ms=0
        ),
    )
    pr.register(
        ("getent", "group", "docker"),
        ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("groupadd", "docker"),
        ProcessResult(
            exit_code=9, stdout="", stderr="group exists", duration_ms=1
        ),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(
            user="alice",
            group="docker",
            create_group_if_missing=True,
        ),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "GROUP_CREATE_FAILED"
