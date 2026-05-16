from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def linux_runner_with_executables() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    for name in ("useradd", "usermod", "userdel", "getent"):
        pr.register_executable(name)
    return pr


def darwin_runner_with_executables() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    for name in ("dscl", "dseditgroup"):
        pr.register_executable(name)
    return pr


def register_linux_user(
    pr: ScriptedProcessRunner,
    username: str,
    *,
    uid: int = 1500,
    gid: int = 1500,
    home: str = "/home/alice",
    shell: str = "/bin/bash",
) -> None:
    pr.register(
        ("getent", "passwd", username),
        ProcessResult(
            exit_code=0,
            stdout=f"{username}:x:{uid}:{gid}::{home}:{shell}\n",
            stderr="",
            duration_ms=0,
        ),
    )


def register_linux_user_missing(pr: ScriptedProcessRunner, username: str) -> None:
    pr.register(
        ("getent", "passwd", username),
        ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0),
    )


def register_linux_uid_owner(
    pr: ScriptedProcessRunner, uid: int, owner: str | None,
    *,
    owner_uid: int | None = None,
    owner_gid: int = 1500,
    home: str = "/home/other",
    shell: str = "/bin/bash",
) -> None:
    if owner is None:
        pr.register(
            ("getent", "passwd", str(uid)),
            ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0),
        )
        return
    real_uid = owner_uid if owner_uid is not None else uid
    pr.register(
        ("getent", "passwd", str(uid)),
        ProcessResult(
            exit_code=0,
            stdout=f"{owner}:x:{real_uid}:{owner_gid}::{home}:{shell}\n",
            stderr="",
            duration_ms=0,
        ),
    )


def register_linux_group(
    pr: ScriptedProcessRunner,
    group: str,
    *,
    gid: int = 2000,
    members: tuple[str, ...] = (),
) -> None:
    pr.register(
        ("getent", "group", group),
        ProcessResult(
            exit_code=0,
            stdout=f"{group}:x:{gid}:{','.join(members)}\n",
            stderr="",
            duration_ms=0,
        ),
    )


def register_linux_group_missing(pr: ScriptedProcessRunner, group: str) -> None:
    pr.register(
        ("getent", "group", group),
        ProcessResult(exit_code=2, stdout="", stderr="", duration_ms=0),
    )


def register_darwin_user(
    pr: ScriptedProcessRunner,
    username: str,
    *,
    uid: int = 501,
    gid: int = 20,
    home: str = "/Users/alice",
    shell: str = "/bin/bash",
) -> None:
    body = (
        f"NFSHomeDirectory: {home}\n"
        f"PrimaryGroupID: {gid}\n"
        f"UniqueID: {uid}\n"
        f"UserShell: {shell}\n"
    )
    pr.register(
        ("dscl", ".", "-read", f"/Users/{username}"),
        ProcessResult(exit_code=0, stdout=body, stderr="", duration_ms=0),
    )


def register_darwin_user_missing(pr: ScriptedProcessRunner, username: str) -> None:
    pr.register(
        ("dscl", ".", "-read", f"/Users/{username}"),
        ProcessResult(
            exit_code=2,
            stdout="",
            stderr="DS Error: -14136 (eDSRecordNotFound)\n",
            duration_ms=0,
        ),
    )


def register_darwin_uid_owner(
    pr: ScriptedProcessRunner, uid: int, owner: str | None
) -> None:
    if owner is None:
        pr.register(
            ("dscl", ".", "-search", "/Users", "UniqueID", str(uid)),
            ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
        )
        return
    pr.register(
        ("dscl", ".", "-search", "/Users", "UniqueID", str(uid)),
        ProcessResult(
            exit_code=0,
            stdout=f"{owner}\t\tUniqueID = ({uid})\n",
            stderr="",
            duration_ms=0,
        ),
    )


def register_darwin_group(
    pr: ScriptedProcessRunner,
    group: str,
    *,
    gid: int = 80,
    members: tuple[str, ...] = (),
) -> None:
    pr.register(
        ("dscl", ".", "-read", f"/Groups/{group}", "PrimaryGroupID"),
        ProcessResult(
            exit_code=0,
            stdout=f"PrimaryGroupID: {gid}\n",
            stderr="",
            duration_ms=0,
        ),
    )
    members_line = (
        f"GroupMembership: {' '.join(members)}\n" if members else "GroupMembership:\n"
    )
    pr.register(
        ("dscl", ".", "-read", f"/Groups/{group}", "GroupMembership"),
        ProcessResult(
            exit_code=0, stdout=members_line, stderr="", duration_ms=0
        ),
    )


__all__ = [
    "Path",
    "darwin_runner_with_executables",
    "linux_runner_with_executables",
    "register_darwin_group",
    "register_darwin_uid_owner",
    "register_darwin_user",
    "register_darwin_user_missing",
    "register_linux_group",
    "register_linux_group_missing",
    "register_linux_uid_owner",
    "register_linux_user",
    "register_linux_user_missing",
]
