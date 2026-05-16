from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
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


class _StatefulUserLinux(ScriptedProcessRunner):
    """Linux runner where `useradd <username>` flips later getent probes to
    return that user."""

    def __init__(self, username: str, uid: int = 1500) -> None:
        super().__init__()
        for name in ("useradd", "usermod", "userdel", "getent"):
            self.register_executable(name)
        self._username = username
        self._uid = uid
        self._exists = False
        register_linux_user_missing(self, username)
        register_linux_uid_owner(self, uid, None)

    def _mark_exists(self) -> None:
        self._exists = True
        # Re-register so probes return the user now.
        self.reset_scripts_for(("getent", "passwd"))
        register_linux_user(
            self, self._username,
            uid=self._uid, gid=self._uid,
            home=f"/home/{self._username}", shell="/bin/bash",
        )

    @override
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult:
        argv_tuple = tuple(argv)
        if argv_tuple[:1] == ("useradd",):
            self._mark_exists()
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


def test_transition_creates_user_on_linux() -> None:
    pr = _StatefulUserLinux("alice", uid=1500)
    changer = EnsureUserStateChanger(
        EnsureUserParameters(username="alice", uid=1500),
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert result.details["created_by_us"] == "true"
    assert result.details["uid"] == "1500"
    useradd_calls = [c for c in pr.calls if c.argv[:1] == ("useradd",)]
    assert len(useradd_calls) == 1
    assert "alice" in useradd_calls[0].argv
    assert changer.created_by_us is True


def test_transition_records_attributes_when_user_already_exists() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice", uid=1500)
    changer = EnsureUserStateChanger(
        EnsureUserParameters(username="alice"),
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert result.details["created_by_us"] == "false"
    assert changer.created_by_us is False
    assert not any(c.argv[:1] == ("useradd",) for c in pr.calls)


class _StatefulUserDarwin(ScriptedProcessRunner):
    """Darwin runner where the first `dscl . -create /Users/<name>` flips
    later `dscl . -read /Users/<name>` probes to return that user."""

    def __init__(
        self,
        username: str,
        *,
        uid: int = 700,
        gid: int = 20,
        home: str = "/Users/alice",
        shell: str = "/bin/zsh",
    ) -> None:
        super().__init__()
        for name in ("dscl", "dseditgroup"):
            self.register_executable(name)
        self._username = username
        self._uid = uid
        self._gid = gid
        self._home = home
        self._shell = shell
        self._exists = False
        register_darwin_user_missing(self, username)
        register_darwin_uid_owner(self, uid, None)

    def _mark_exists(self) -> None:
        self._exists = True
        self.reset_scripts_for(("dscl", ".", "-read", f"/Users/{self._username}"))
        register_darwin_user(
            self,
            self._username,
            uid=self._uid,
            gid=self._gid,
            home=self._home,
            shell=self._shell,
        )

    @override
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult:
        argv_tuple = tuple(argv)
        create_root = ("dscl", ".", "-create", f"/Users/{self._username}")
        if argv_tuple == create_root:
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            self._mark_exists()
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


def test_transition_creates_user_on_darwin_with_multiple_dscl_calls() -> None:
    pr = _StatefulUserDarwin("alice", uid=700, gid=20)
    register_darwin_group(pr, "staff", gid=20)
    changer = EnsureUserStateChanger(
        EnsureUserParameters(
            username="alice",
            uid=700,
            home=Path("/Users/alice"),
            shell=Path("/bin/zsh"),
            primary_group="staff",
        ),
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.darwin(),
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert result.details["created_by_us"] == "true"
    assert result.details["uid"] == "700"
    assert changer.created_by_us is True

    create_calls = [c for c in pr.calls if c.argv[:3] == ("dscl", ".", "-create")]
    create_targets = [c.argv for c in create_calls]
    user_path = "/Users/alice"
    # Root record + each attribute we requested (uid, primary gid, home, shell).
    assert ("dscl", ".", "-create", user_path) in create_targets
    assert ("dscl", ".", "-create", user_path, "UniqueID", "700") in create_targets
    assert ("dscl", ".", "-create", user_path, "PrimaryGroupID", "20") in create_targets
    assert ("dscl", ".", "-create", user_path, "NFSHomeDirectory", user_path) in create_targets
    assert ("dscl", ".", "-create", user_path, "UserShell", "/bin/zsh") in create_targets


def test_transition_adds_missing_supplementary_groups_on_linux() -> None:
    pr = linux_runner_with_executables()
    register_linux_user(pr, "alice")
    register_linux_group(pr, "docker", gid=999, members=())
    register_linux_group(pr, "sudo", gid=27, members=("alice",))
    changer = EnsureUserStateChanger(
        EnsureUserParameters(
            username="alice",
            supplementary_groups=("docker", "sudo"),
        ),
        process_runner=pr,
        file_system=InMemoryFileSystem(),
        env=ScriptedEnv.linux(),
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    usermod_calls = [c for c in pr.calls if c.argv[:1] == ("usermod",)]
    # Only docker missing — sudo already has alice as member.
    assert len(usermod_calls) == 1
    assert usermod_calls[0].argv == ("usermod", "-aG", "docker", "alice")
