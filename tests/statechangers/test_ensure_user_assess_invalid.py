from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureUserParameters,
    EnsureUserStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._ensure_user_helpers import (
    linux_runner_with_executables,
    register_linux_group,
    register_linux_group_missing,
    register_linux_uid_owner,
    register_linux_user,
    register_linux_user_missing,
)


def _changer(
    params: EnsureUserParameters, pr: ScriptedProcessRunner
) -> EnsureUserStateChanger:
    return EnsureUserStateChanger(
        params,
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )


def test_invalid_username() -> None:
    pr = linux_runner_with_executables()
    changer = _changer(EnsureUserParameters(username="Alice!"), pr)
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("invalid username" in i for i in assess.issues)


def test_required_binaries_missing_on_linux() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("getent")  # only getent
    changer = _changer(EnsureUserParameters(username="alice"), pr)
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("useradd not on PATH" in i for i in assess.issues)
    assert any("usermod not on PATH" in i for i in assess.issues)


def test_uid_in_use_by_different_user_when_creating() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_uid_owner(pr, 1500, "bob")
    changer = _changer(
        EnsureUserParameters(username="alice", uid=1500), pr
    )
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("uid 1500 in use by bob" in i for i in assess.issues)


def test_uid_owned_by_target_user_is_ok() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500)
    register_linux_uid_owner(pr, 1500, "alice")
    changer = _changer(
        EnsureUserParameters(username="alice", uid=1500), pr
    )
    assess = changer.assess_state()
    # uid matches, user exists with no other params → ALREADY_APPLIED
    assert assess.state is ExistingState.ALREADY_APPLIED


def test_attribute_drift_enforced_lists_each_diff() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(
        pr, "alice", uid=1500, gid=1500, home="/home/alice", shell="/bin/bash"
    )
    register_linux_uid_owner(pr, 2000, None)
    register_linux_group(pr, "wheel", gid=10)
    changer = _changer(
        EnsureUserParameters(
            username="alice",
            uid=2000,
            home=Path("/home/other"),
            shell=Path("/bin/zsh"),
            primary_group="wheel",
            enforce_attributes=True,
        ),
        pr,
    )
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("uid differs" in i for i in assess.issues)
    assert any("home differs" in i for i in assess.issues)
    assert any("shell differs" in i for i in assess.issues)
    assert any("primary group differs" in i for i in assess.issues)


def test_attribute_drift_ignored_when_enforce_attributes_false() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500)
    changer = _changer(
        EnsureUserParameters(
            username="alice", uid=9999, enforce_attributes=False
        ),
        pr,
    )
    assess = changer.assess_state()
    assert assess.state is ExistingState.ALREADY_APPLIED


def test_supplementary_group_missing_is_invalid() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice")
    register_linux_group_missing(pr, "ghosts")
    changer = _changer(
        EnsureUserParameters(
            username="alice", supplementary_groups=("ghosts",)
        ),
        pr,
    )
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("ghosts" in i for i in assess.issues)


def test_primary_group_missing_is_invalid() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_group_missing(pr, "wheel")
    changer = _changer(
        EnsureUserParameters(username="alice", primary_group="wheel"), pr
    )
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert any("primary group does not exist" in i for i in assess.issues)


def test_multiple_issues_collected_in_one_pass() -> None:
    pr = linux_runner_with_executables()
    register_linux_user_missing(pr, "alice")
    register_linux_uid_owner(pr, 1500, "bob")
    register_linux_group_missing(pr, "ghosts")
    register_linux_group_missing(pr, "wheel")
    changer = _changer(
        EnsureUserParameters(
            username="alice",
            uid=1500,
            primary_group="wheel",
            supplementary_groups=("ghosts",),
        ),
        pr,
    )
    assess = changer.assess_state()
    assert assess.state is ExistingState.INVALID
    assert len(assess.issues) >= 3
