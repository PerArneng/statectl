from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureUserParameters,
    EnsureUserStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._ensure_user_helpers import (
    darwin_runner_with_executables,
    linux_runner_with_executables,
    register_darwin_group,
    register_darwin_uid_owner,
    register_darwin_user,
    register_darwin_user_missing,
    register_linux_group,
    register_linux_uid_owner,
    register_linux_user,
    register_linux_user_missing,
)


def _linux_changer(
    params: EnsureUserParameters, pr: ScriptedProcessRunner
) -> EnsureUserStateChanger:
    return EnsureUserStateChanger(
        params,
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )


def _darwin_changer(
    params: EnsureUserParameters, pr: ScriptedProcessRunner
) -> EnsureUserStateChanger:
    return EnsureUserStateChanger(
        params,
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.darwin(),
    )


def test_ready_when_user_absent_linux() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_uid_owner(pr, 1500, None)
    assess = _linux_changer(
        EnsureUserParameters(username="alice", uid=1500), pr
    ).assess_state()
    assert assess.state is ExistingState.READY


def test_ready_when_user_absent_darwin() -> None:
    pr = darwin_runner_with_executables()
    register_darwin_user_missing(pr, "alice")
    register_darwin_uid_owner(pr, 700, None)
    assess = _darwin_changer(
        EnsureUserParameters(username="alice", uid=700), pr
    ).assess_state()
    assert assess.state is ExistingState.READY


def test_already_applied_when_user_exists_matches_linux() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(
        pr, "alice", uid=1500, gid=2000,
        home="/home/alice", shell="/bin/bash",
    )
    register_linux_group(pr, "alice-group", gid=2000)
    assess = _linux_changer(
        EnsureUserParameters(
            username="alice",
            uid=1500,
            home=Path("/home/alice"),
            shell=Path("/bin/bash"),
            primary_group="alice-group",
        ),
        pr,
    ).assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_user_exists_matches_darwin() -> None:
    pr = darwin_runner_with_executables()
    register_darwin_user(
        pr, "alice", uid=501, gid=20,
        home="/Users/alice", shell="/bin/zsh",
    )
    register_darwin_group(pr, "staff", gid=20)
    assess = _darwin_changer(
        EnsureUserParameters(
            username="alice",
            uid=501,
            home=Path("/Users/alice"),
            shell=Path("/bin/zsh"),
            primary_group="staff",
        ),
        pr,
    ).assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED


def test_ready_when_user_exists_but_missing_supplementary_group() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice")
    register_linux_group(pr, "docker", gid=999, members=())
    assess = _linux_changer(
        EnsureUserParameters(
            username="alice", supplementary_groups=("docker",)
        ),
        pr,
    ).assess_state()
    assert assess.state is ExistingState.READY
    assert "docker" in assess.description


def test_already_applied_when_user_already_in_supplementary_group() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice")
    register_linux_group(pr, "docker", gid=999, members=("alice", "bob"))
    assess = _linux_changer(
        EnsureUserParameters(
            username="alice", supplementary_groups=("docker",)
        ),
        pr,
    ).assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED


@pytest.mark.parametrize("enforce", [True, False])
def test_minimum_params_only_username(enforce: bool) -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice")
    assess = _linux_changer(
        EnsureUserParameters(username="alice", enforce_attributes=enforce), pr
    ).assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED
