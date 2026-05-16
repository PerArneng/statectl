from __future__ import annotations

import pytest

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipStateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _linux_changer(
    *, user_groups: str, group_exists: bool = True
) -> EnsureGroupMembershipStateChanger:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("getent")
    pr.register_executable("usermod")
    pr.register_executable("groupadd")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0, stdout=user_groups + "\n", stderr="", duration_ms=0
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
    return EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="docker"),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )


@pytest.mark.parametrize(
    ("user_groups", "expected"),
    [
        ("alice users docker", ExistingState.ALREADY_APPLIED),
        ("alice users", ExistingState.READY),
        ("docker", ExistingState.ALREADY_APPLIED),
        ("", ExistingState.READY),
    ],
)
def test_membership_truth_table(user_groups: str, expected: ExistingState) -> None:
    assert _linux_changer(user_groups=user_groups).assess_state().state is expected


def test_already_applied_on_darwin() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("id")
    pr.register_executable("dseditgroup")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0,
            stdout="alice staff wheel\n",
            stderr="",
            duration_ms=0,
        ),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="wheel"),
        process_runner=pr,
        env=ScriptedEnv.darwin(),
    )

    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED
