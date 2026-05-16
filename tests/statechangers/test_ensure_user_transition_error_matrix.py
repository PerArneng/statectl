from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureUserParameters,
    EnsureUserStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.statechangers._ensure_user_helpers import (
    linux_runner_with_executables,
    register_linux_uid_owner,
    register_linux_user_missing,
)


def _changer(
    params: EnsureUserParameters, pr: object
) -> EnsureUserStateChanger:
    return EnsureUserStateChanger(
        params,
        process_runner=pr,  # type: ignore[arg-type]
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )


def test_useradd_failure_maps_to_user_create_failed() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_uid_owner(pr, 1500, None)
    pr.register(
        ("useradd",),
        ProcessResult(
            exit_code=4, stdout="", stderr="UID already in use\n", duration_ms=0
        ),
    )
    result = _changer(
        EnsureUserParameters(username="alice", uid=1500), pr
    ).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "USER_CREATE_FAILED"
    assert result.details["stderr"].startswith("UID already")


def test_uid_conflict_detected_before_useradd() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_uid_owner(pr, 1500, "bob")
    result = _changer(
        EnsureUserParameters(username="alice", uid=1500), pr
    ).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "UID_CONFLICT"


def test_usermod_failure_maps_to_group_membership_failed() -> None:
    from tests.statechangers._ensure_user_helpers import (
        register_linux_group,
        register_linux_user,
    )

    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice")
    register_linux_group(pr, "docker", gid=999, members=())
    pr.register(
        ("usermod",),
        ProcessResult(
            exit_code=6, stdout="", stderr="no such group\n", duration_ms=0
        ),
    )
    result = _changer(
        EnsureUserParameters(
            username="alice", supplementary_groups=("docker",)
        ),
        pr,
    ).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "GROUP_MEMBERSHIP_FAILED"
