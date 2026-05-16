from __future__ import annotations

from pathlib import Path
from typing import override

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureGroupMembershipParameters,
    EnsureGroupMembershipStateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _linux_rig(
    *,
    user: str = "alice",
    group: str = "docker",
    user_exists: bool = True,
    user_groups: str = "alice users",
    group_exists: bool = True,
    create_group_if_missing: bool = False,
    id_on_path: bool = True,
    getent_on_path: bool = True,
    usermod_on_path: bool = True,
    groupadd_on_path: bool = True,
) -> EnsureGroupMembershipStateChanger:
    pr = ScriptedProcessRunner()
    if id_on_path:
        pr.register_executable("id")
    if getent_on_path:
        pr.register_executable("getent")
    if usermod_on_path:
        pr.register_executable("usermod")
    if groupadd_on_path:
        pr.register_executable("groupadd")
    if user_exists:
        pr.register(
            ("id", "-nG", user),
            ProcessResult(
                exit_code=0, stdout=user_groups + "\n", stderr="", duration_ms=0
            ),
        )
    else:
        pr.register(
            ("id", "-nG", user),
            ProcessResult(
                exit_code=1, stdout="", stderr="no such user", duration_ms=0
            ),
        )
    pr.register(
        ("getent", "group", group),
        ProcessResult(
            exit_code=0 if group_exists else 2,
            stdout=f"{group}:x:999:\n" if group_exists else "",
            stderr="",
            duration_ms=0,
        ),
    )
    return EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(
            user=user,
            group=group,
            create_group_if_missing=create_group_if_missing,
        ),
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )


def test_invalid_when_user_name_has_metacharacters() -> None:
    changer = _linux_rig(user="alice; rm -rf /")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid user name" in i for i in assess.issues)


def test_invalid_when_group_name_has_metacharacters() -> None:
    changer = _linux_rig(group="docker; rm -rf /")

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid group name" in i for i in assess.issues)


def test_invalid_when_user_does_not_exist() -> None:
    changer = _linux_rig(user_exists=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("user not found" in i for i in assess.issues)


def test_invalid_when_group_missing_and_create_false() -> None:
    changer = _linux_rig(group_exists=False, create_group_if_missing=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("group not found" in i for i in assess.issues)


def test_ready_when_group_missing_and_create_true() -> None:
    changer = _linux_rig(group_exists=False, create_group_if_missing=True)

    assess = changer.assess_state()

    assert assess.state is ExistingState.READY


def test_invalid_when_groupadd_not_on_path_with_create_true() -> None:
    changer = _linux_rig(
        group_exists=False,
        create_group_if_missing=True,
        groupadd_on_path=False,
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("groupadd not on PATH" in i for i in assess.issues)


def test_invalid_when_required_tools_missing() -> None:
    changer = _linux_rig(usermod_on_path=False, getent_on_path=False)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    joined = "\n".join(assess.issues)
    assert "usermod not on PATH" in joined
    assert "getent not on PATH" in joined


def test_invalid_collects_input_issues_in_one_pass() -> None:
    changer = _linux_rig(
        user="alice; rm -rf /", group="docker; rm -rf /"
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    joined = "\n".join(assess.issues)
    assert "invalid user name" in joined
    assert "invalid group name" in joined


class _RunnerWithMissingTool(ScriptedProcessRunner):
    def __init__(self, hidden: str) -> None:
        super().__init__()
        self._hidden = hidden

    @override
    def which(self, name: str) -> Path | None:
        if name == self._hidden:
            return None
        return super().which(name)


def test_invalid_when_dseditgroup_not_on_path_on_darwin() -> None:
    pr = _RunnerWithMissingTool("dseditgroup")
    pr.register_executable("id")
    pr.register_executable("dseditgroup")
    pr.register(
        ("id", "-nG", "alice"),
        ProcessResult(
            exit_code=0, stdout="alice users\n", stderr="", duration_ms=0
        ),
    )
    pr.register(
        ("dseditgroup", "-o", "read", "wheel"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    changer = EnsureGroupMembershipStateChanger(
        EnsureGroupMembershipParameters(user="alice", group="wheel"),
        process_runner=pr,
        env=ScriptedEnv.darwin(),
    )

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("dseditgroup not on PATH" in i for i in assess.issues)
