from __future__ import annotations

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _inner() -> ScriptedProcessRunner:
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
            exit_code=0, stdout="docker:x:999:\n", stderr="", duration_ms=0
        ),
    )
    pr.register(
        ("usermod", "-aG", "docker", "alice"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    return pr


@pytest.mark.parametrize(
    "exc",
    [
        ProcessNotFound("not found", argv=("usermod",)),
        ProcessTimeout("timed out", argv=("usermod",)),
        ProcessDecodeError("decode error", argv=("usermod",)),
        ProcessLaunchError("launch error", argv=("usermod",)),
    ],
)
def test_each_typed_process_error_maps_to_membership_add_failed(
    exc: Exception,
) -> None:
    failing = FailingProcessRunner(_inner())
    failing.fail("run", exc)

    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="docker"),
        process_runner=failing,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "MEMBERSHIP_ADD_FAILED"


def test_unexpected_exception_propagates() -> None:
    failing = FailingProcessRunner(_inner())
    failing.fail("run", RuntimeError("boom"))

    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="docker"),
        process_runner=failing,
        env=ScriptedEnv.linux(),
    )

    with pytest.raises(RuntimeError, match="boom"):
        changer.transition()
