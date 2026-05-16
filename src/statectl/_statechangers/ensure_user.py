from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl._interfaces.env import Env, Platform
from statectl._interfaces.fs import FileSystem
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealEnv, RealFileSystem, RealProcessRunner
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


_OUTPUT_CAP = 4096
# Trailing `$` is allowed so Samba machine accounts (e.g. `host$`) are accepted.
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]*\$?$")
_USERNAME_MAX_LEN = 32
_LINUX_BINARIES: tuple[str, ...] = ("useradd", "usermod", "getent")
_DARWIN_BINARIES: tuple[str, ...] = ("dscl", "dseditgroup")
_USER_CREATE_FAILED = "USER_CREATE_FAILED"
_GROUP_MEMBERSHIP_FAILED = "GROUP_MEMBERSHIP_FAILED"
_UID_CONFLICT = "UID_CONFLICT"
_USER_LOOKUP_FAILED = "USER_LOOKUP_FAILED"
_USER_DELETE_FAILED = "USER_DELETE_FAILED"


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class EnsureUserParameters(Parameters):
    """Parameters describing a desired local user account.

    Platform asymmetries to be aware of:
    - Linux: `useradd -d <home> -m` creates the home directory on disk.
    - macOS: dscl writes `NFSHomeDirectory` but does *not* create the directory;
      drivers needing the directory must run `createhomedir` separately.
    - Neither platform sets a password; the account is created without one.
    """

    username: str
    uid: int | None = None
    home: Path | None = None
    shell: Path | None = None
    primary_group: str | None = None
    supplementary_groups: tuple[str, ...] = ()
    system: bool = False
    enforce_attributes: bool = True


@dataclass(frozen=True)
class _UserInfo:
    uid: int
    home: Path
    shell: Path
    primary_gid: int


@dataclass(frozen=True)
class _ProbeError:
    message: str


def _probe(pr: ProcessRunner, argv: tuple[str, ...]) -> ProcessResult | _ProbeError:
    try:
        return pr.run(argv)
    except ProcessNotFound as e:
        return _ProbeError(f"probe failed (not found): {e}")
    except ProcessTimeout as e:
        return _ProbeError(f"probe timed out: {e}")
    except ProcessDecodeError as e:
        return _ProbeError(f"probe decode error: {e}")
    except ProcessLaunchError as e:
        return _ProbeError(f"probe launch error: {e}")


def _required_binaries(platform: Platform) -> tuple[str, ...]:
    return _DARWIN_BINARIES if platform == "darwin" else _LINUX_BINARIES


def _parse_getent_passwd(stdout: str) -> _UserInfo | None:
    line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    if not line:
        return None
    parts = line.split(":")
    if len(parts) < 7:
        return None
    try:
        uid = int(parts[2])
        gid = int(parts[3])
    except ValueError:
        return None
    return _UserInfo(uid=uid, home=Path(parts[5]), shell=Path(parts[6]), primary_gid=gid)


def _dscl_field(stdout: str, key: str) -> str | None:
    for raw in stdout.splitlines():
        text = raw.strip()
        if text.startswith(f"{key}:"):
            value = text.split(":", 1)[1].strip()
            return value or None
    return None


def _parse_dscl_user(stdout: str) -> _UserInfo | None:
    uid_s = _dscl_field(stdout, "UniqueID")
    gid_s = _dscl_field(stdout, "PrimaryGroupID")
    home = _dscl_field(stdout, "NFSHomeDirectory")
    shell = _dscl_field(stdout, "UserShell")
    if uid_s is None or gid_s is None or home is None or shell is None:
        return None
    try:
        uid = int(uid_s)
        gid = int(gid_s)
    except ValueError:
        return None
    return _UserInfo(uid=uid, home=Path(home), shell=Path(shell), primary_gid=gid)


def _probe_user(
    pr: ProcessRunner, platform: Platform, username: str
) -> _UserInfo | None | _ProbeError:
    if platform == "darwin":
        argv: tuple[str, ...] = ("dscl", ".", "-read", f"/Users/{username}")
        result = _probe(pr, argv)
        if isinstance(result, _ProbeError):
            return result
        if result.exit_code != 0:
            return None
        return _parse_dscl_user(result.stdout)
    argv = ("getent", "passwd", username)
    result = _probe(pr, argv)
    if isinstance(result, _ProbeError):
        return result
    if result.exit_code != 0:
        return None
    return _parse_getent_passwd(result.stdout)


def _probe_uid_owner(
    pr: ProcessRunner, platform: Platform, uid: int
) -> str | None | _ProbeError:
    """Returns the username already holding `uid`, None if unused, or _ProbeError."""
    if platform == "darwin":
        argv: tuple[str, ...] = (
            "dscl", ".", "-search", "/Users", "UniqueID", str(uid),
        )
        result = _probe(pr, argv)
        if isinstance(result, _ProbeError):
            return result
        if result.exit_code != 0:
            return None
        text = result.stdout.strip()
        if not text:
            return None
        name = text.splitlines()[0].split()[0].strip()
        return name or None
    argv = ("getent", "passwd", str(uid))
    result = _probe(pr, argv)
    if isinstance(result, _ProbeError):
        return result
    if result.exit_code != 0:
        return None
    info = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not info:
        return None
    return info.split(":")[0] or None


def _probe_group_gid(
    pr: ProcessRunner, platform: Platform, group: str
) -> int | None | _ProbeError:
    if platform == "darwin":
        argv: tuple[str, ...] = (
            "dscl", ".", "-read", f"/Groups/{group}", "PrimaryGroupID",
        )
        result = _probe(pr, argv)
        if isinstance(result, _ProbeError):
            return result
        if result.exit_code != 0:
            return None
        gid_s = _dscl_field(result.stdout, "PrimaryGroupID")
        if gid_s is None:
            return None
        try:
            return int(gid_s)
        except ValueError:
            return None
    argv = ("getent", "group", group)
    result = _probe(pr, argv)
    if isinstance(result, _ProbeError):
        return result
    if result.exit_code != 0:
        return None
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = line.split(":")
    if len(parts) < 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def _probe_group_members(
    pr: ProcessRunner, platform: Platform, group: str
) -> set[str] | None | _ProbeError:
    """Returns the set of usernames in `group`, None if group missing, or _ProbeError."""
    if platform == "darwin":
        argv: tuple[str, ...] = (
            "dscl", ".", "-read", f"/Groups/{group}", "GroupMembership",
        )
        result = _probe(pr, argv)
        if isinstance(result, _ProbeError):
            return result
        if result.exit_code != 0:
            return None
        for raw in result.stdout.splitlines():
            text = raw.strip()
            if text.startswith("GroupMembership:"):
                tokens = text.split(":", 1)[1].split()
                return set(tokens)
        return set()
    argv = ("getent", "group", group)
    result = _probe(pr, argv)
    if isinstance(result, _ProbeError):
        return result
    if result.exit_code != 0:
        return None
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = line.split(":")
    if len(parts) < 4:
        return None
    members = parts[3].strip()
    return set(filter(None, (m.strip() for m in members.split(","))))


def _useradd_argv(params: EnsureUserParameters) -> tuple[str, ...]:
    argv: list[str] = ["useradd"]
    if params.system:
        argv.append("-r")
    if params.uid is not None:
        argv.extend(["-u", str(params.uid)])
    if params.home is not None:
        argv.extend(["-d", str(params.home), "-m"])
    if params.shell is not None:
        argv.extend(["-s", str(params.shell)])
    if params.primary_group is not None:
        argv.extend(["-g", params.primary_group])
    argv.append(params.username)
    return tuple(argv)


def _dscl_create_argvs(
    params: EnsureUserParameters, primary_gid: int | None
) -> list[tuple[str, ...]]:
    user_path = f"/Users/{params.username}"
    argvs: list[tuple[str, ...]] = [("dscl", ".", "-create", user_path)]
    if params.uid is not None:
        argvs.append(("dscl", ".", "-create", user_path, "UniqueID", str(params.uid)))
    if primary_gid is not None:
        argvs.append(("dscl", ".", "-create", user_path, "PrimaryGroupID", str(primary_gid)))
    if params.home is not None:
        argvs.append(("dscl", ".", "-create", user_path, "NFSHomeDirectory", str(params.home)))
    if params.shell is not None:
        argvs.append(("dscl", ".", "-create", user_path, "UserShell", str(params.shell)))
    if params.system:
        argvs.append(("dscl", ".", "-create", user_path, "IsHidden", "1"))
    return argvs


def _supp_group_add_argv(
    platform: Platform, username: str, group: str
) -> tuple[str, ...]:
    if platform == "darwin":
        return ("dseditgroup", "-o", "edit", "-a", username, "-t", "user", group)
    return ("usermod", "-aG", group, username)


def _userdel_argvs(platform: Platform, username: str) -> list[tuple[str, ...]]:
    if platform == "darwin":
        return [("dscl", ".", "-delete", f"/Users/{username}")]
    return [("userdel", username)]


def _run_failure_result(
    code: str, argv: tuple[str, ...], result: ProcessResult
) -> Result:
    return Result(
        status=ResultStatus.FAILURE,
        code=code,
        message=f"{argv[0]} exited {result.exit_code}",
        details={
            "argv": " ".join(argv),
            "exit_code": str(result.exit_code),
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
        },
    )


def _run_step(
    pr: ProcessRunner, argv: tuple[str, ...], code: str
) -> tuple[ProcessResult | None, Result | None]:
    try:
        result = pr.run(argv)
    except ProcessNotFound as e:
        return None, Result.failure(code, str(e))
    except ProcessTimeout as e:
        return None, Result.failure(code, f"timed out: {e}")
    except ProcessDecodeError as e:
        return None, Result.failure(code, f"decode error: {e}")
    except ProcessLaunchError as e:
        return None, Result.failure(code, f"launch error: {e}")
    if result.exit_code != 0:
        return result, _run_failure_result(code, argv, result)
    return result, None


def _attribute_diffs(
    params: EnsureUserParameters,
    info: _UserInfo,
    primary_gid: int | None,
) -> list[str]:
    diffs: list[str] = []
    if params.uid is not None and info.uid != params.uid:
        diffs.append(
            f"uid differs: requested {params.uid}, current {info.uid}"
        )
    if params.home is not None and info.home != params.home:
        diffs.append(
            f"home differs: requested {params.home}, current {info.home}"
        )
    if params.shell is not None and info.shell != params.shell:
        diffs.append(
            f"shell differs: requested {params.shell}, current {info.shell}"
        )
    if primary_gid is not None and info.primary_gid != primary_gid:
        diffs.append(
            f"primary group differs: requested {params.primary_group} "
            f"(gid {primary_gid}), current gid {info.primary_gid}"
        )
    return diffs


def _rollback_drift_issues(existing: _UserInfo, recorded: _UserInfo) -> list[str]:
    issues: list[str] = []
    if existing.uid != recorded.uid:
        issues.append(
            f"uid changed since creation: recorded {recorded.uid}, "
            f"current {existing.uid}"
        )
    if existing.home != recorded.home:
        issues.append(
            f"home changed since creation: recorded {recorded.home}, "
            f"current {existing.home}"
        )
    return issues


class EnsureUserStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureUserParameters,
        process_runner: ProcessRunner | None = None,
        file_system: FileSystem | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._fs: FileSystem = file_system or RealFileSystem()
        self._env: Env = env or RealEnv()
        self._created_by_us: bool = False
        self._recorded_info: _UserInfo | None = None

    @property
    def params(self) -> EnsureUserParameters:
        return self._params

    @property
    def created_by_us(self) -> bool:
        return self._created_by_us

    @override
    def name(self) -> str:
        return f"ensure-user:{self._params.username}"

    def _assess_platform(self, platform: Platform) -> list[str]:
        issues: list[str] = []
        for binary in _required_binaries(platform):
            if self._pr.which(binary) is None:
                issues.append(f"{binary} not on PATH")
        return issues

    def _assess_inputs(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if not _USERNAME_RE.match(params.username):
            issues.append(f"invalid username: {params.username!r}")
        elif len(params.username) > _USERNAME_MAX_LEN:
            issues.append(
                f"username too long ({len(params.username)} > "
                f"{_USERNAME_MAX_LEN}): {params.username!r}"
            )
        return issues

    def _assess_uid_conflict(
        self, platform: Platform, existing: _UserInfo | None
    ) -> list[str]:
        params = self._params
        if params.uid is None:
            return []
        owner = _probe_uid_owner(self._pr, platform, params.uid)
        if isinstance(owner, _ProbeError):
            return [owner.message]
        if owner is None:
            return []
        if (
            existing is not None
            and owner == params.username
            and existing.uid == params.uid
        ):
            return []
        return [f"uid {params.uid} in use by {owner}"]

    def _assess_primary_gid(
        self, platform: Platform
    ) -> tuple[int | None, list[str]]:
        params = self._params
        if params.primary_group is None:
            return None, []
        gid = _probe_group_gid(self._pr, platform, params.primary_group)
        if isinstance(gid, _ProbeError):
            return None, [gid.message]
        if gid is None:
            return None, [f"primary group does not exist: {params.primary_group}"]
        return gid, []

    def _assess_supp_groups(
        self, platform: Platform
    ) -> tuple[list[str], list[str]]:
        """Returns (groups_user_already_in, issues). Groups that don't exist
        produce issues; existing groups are split into already-member vs
        needs-to-be-added (caller decides ALREADY_APPLIED vs READY)."""
        already_in: list[str] = []
        issues: list[str] = []
        for group in self._params.supplementary_groups:
            members = _probe_group_members(self._pr, platform, group)
            if isinstance(members, _ProbeError):
                issues.append(members.message)
                continue
            if members is None:
                issues.append(f"supplementary group does not exist: {group}")
                continue
            if self._params.username in members:
                already_in.append(group)
        return already_in, issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        platform = self._env.platform()

        issues = self._assess_inputs()
        issues.extend(self._assess_platform(platform))
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure user",
                issues=issues,
            )

        existing = _probe_user(self._pr, platform, params.username)
        if isinstance(existing, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure user",
                issues=[existing.message],
            )

        primary_gid, gid_issues = self._assess_primary_gid(platform)
        issues.extend(gid_issues)
        issues.extend(self._assess_uid_conflict(platform, existing))

        already_in, supp_issues = self._assess_supp_groups(platform)
        issues.extend(supp_issues)

        if existing is not None and params.enforce_attributes:
            issues.extend(_attribute_diffs(params, existing, primary_gid))

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure user",
                issues=issues,
            )

        if existing is not None:
            missing = [
                g for g in params.supplementary_groups if g not in already_in
            ]
            if not missing:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"user {params.username} already in desired state",
                )
            return StateAssessment(
                state=ExistingState.READY,
                description=(
                    f"user {params.username} exists; need to add to groups: "
                    f"{', '.join(missing)}"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to create user {params.username}",
        )

    def _create_user(
        self, platform: Platform, primary_gid: int | None
    ) -> tuple[list[ProcessResult], Result | None]:
        results: list[ProcessResult] = []
        argvs = (
            _dscl_create_argvs(self._params, primary_gid)
            if platform == "darwin"
            else [_useradd_argv(self._params)]
        )
        for argv in argvs:
            result, failure = _run_step(self._pr, argv, _USER_CREATE_FAILED)
            if failure is not None:
                return results, failure
            assert result is not None
            results.append(result)
        return results, None

    def _add_supplementary_groups(
        self, platform: Platform, groups: list[str]
    ) -> Result | None:
        for group in groups:
            argv = _supp_group_add_argv(platform, self._params.username, group)
            _, failure = _run_step(self._pr, argv, _GROUP_MEMBERSHIP_FAILED)
            if failure is not None:
                return failure
        return None

    def _resolve_primary_gid(
        self, platform: Platform
    ) -> tuple[int | None, Result | None]:
        params = self._params
        if params.primary_group is None:
            return None, None
        gid = _probe_group_gid(self._pr, platform, params.primary_group)
        if isinstance(gid, _ProbeError):
            return None, Result.failure(_USER_CREATE_FAILED, gid.message)
        if gid is None:
            return None, Result.failure(
                _USER_CREATE_FAILED,
                f"primary group does not exist: {params.primary_group}",
            )
        return gid, None

    def _maybe_create_user(
        self, platform: Platform, primary_gid: int | None
    ) -> tuple[bool, Result | None]:
        params = self._params
        if params.uid is not None:
            owner = _probe_uid_owner(self._pr, platform, params.uid)
            if isinstance(owner, _ProbeError):
                return False, Result.failure(_UID_CONFLICT, owner.message)
            if owner is not None:
                return False, Result.failure(
                    _UID_CONFLICT, f"uid {params.uid} in use by {owner}"
                )
        _, failure = self._create_user(platform, primary_gid)
        if failure is not None:
            return False, failure
        return True, None

    @override
    def transition(self) -> Result:
        params = self._params
        platform = self._env.platform()

        existing = _probe_user(self._pr, platform, params.username)
        if isinstance(existing, _ProbeError):
            return Result.failure(_USER_CREATE_FAILED, existing.message)

        primary_gid, gid_failure = self._resolve_primary_gid(platform)
        if gid_failure is not None:
            return gid_failure

        created_by_us = False
        if existing is None:
            created_by_us, failure = self._maybe_create_user(platform, primary_gid)
            if failure is not None:
                return failure

        already_in, _ = self._assess_supp_groups(platform)
        missing = [g for g in params.supplementary_groups if g not in already_in]
        group_failure = self._add_supplementary_groups(platform, missing)
        if group_failure is not None:
            return group_failure

        post = _probe_user(self._pr, platform, params.username)
        if isinstance(post, _ProbeError) or post is None:
            return Result.failure(
                _USER_CREATE_FAILED if created_by_us else _USER_LOOKUP_FAILED,
                "user not visible after transition",
            )
        self._created_by_us = created_by_us
        self._recorded_info = post

        action = "created" if created_by_us else "updated"
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"{action} user {params.username}",
            details={
                "created_by_us": str(created_by_us).lower(),
                "uid": str(post.uid),
                "home": str(post.home),
                "shell": str(post.shell),
            },
        )

    @override
    def rollback(self) -> StateChanger:
        return EnsureUserRollbackStateChanger(
            self._params,
            created_by_us=self._created_by_us,
            recorded_info=self._recorded_info,
            process_runner=self._pr,
            file_system=self._fs,
            env=self._env,
        )


class EnsureUserRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureUserParameters,
        created_by_us: bool = False,
        recorded_info: _UserInfo | None = None,
        process_runner: ProcessRunner | None = None,
        file_system: FileSystem | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._created_by_us = created_by_us
        self._recorded_info = recorded_info
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._fs: FileSystem = file_system or RealFileSystem()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> EnsureUserParameters:
        return self._params

    @property
    def created_by_us(self) -> bool:
        return self._created_by_us

    @override
    def name(self) -> str:
        return f"ensure-user-rollback:{self._params.username}"

    def _rollback_binary_issues(self, platform: Platform) -> list[str]:
        issues: list[str] = []
        for binary in _required_binaries(platform):
            if self._pr.which(binary) is None:
                issues.append(f"{binary} not on PATH")
        if platform == "linux" and self._pr.which("userdel") is None:
            issues.append("userdel not on PATH")
        return issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        platform = self._env.platform()

        if not _USERNAME_RE.match(params.username):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back user",
                issues=[f"invalid username: {params.username!r}"],
            )

        existing = _probe_user(self._pr, platform, params.username)
        if isinstance(existing, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back user",
                issues=[existing.message],
            )
        if existing is None:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"user {params.username} already absent",
            )

        if not self._created_by_us:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"user {params.username} pre-existed; rollback is a no-op"
                ),
            )

        recorded = self._recorded_info
        if recorded is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back user",
                issues=["recorded user info is missing; forward did not run"],
            )

        issues = _rollback_drift_issues(existing, recorded)
        issues.extend(self._rollback_binary_issues(platform))
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back user",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to delete user {params.username}",
        )

    @override
    def transition(self) -> Result:
        params = self._params
        platform = self._env.platform()
        if not self._created_by_us:
            return Result.skipped(
                f"user {params.username} pre-existed; rollback skipped"
            )

        existing = _probe_user(self._pr, platform, params.username)
        if isinstance(existing, _ProbeError):
            return Result.failure(_USER_DELETE_FAILED, existing.message)
        if existing is None:
            return Result.skipped(
                f"user {params.username} already absent"
            )

        for argv in _userdel_argvs(platform, params.username):
            _, failure = _run_step(self._pr, argv, _USER_DELETE_FAILED)
            if failure is not None:
                return failure
        return Result.success(f"deleted user {params.username}")


