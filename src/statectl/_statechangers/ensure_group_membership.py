from __future__ import annotations

import re
from dataclasses import dataclass
from typing import override

from statectl._interfaces.env import Env, Platform
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealEnv, RealProcessRunner
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
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._\-]*\$?$")


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class EnsureGroupMembershipParameters(Parameters):
    user: str
    group: str
    create_group_if_missing: bool = False


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


def _parse_id_groups(stdout: str) -> list[str]:
    return [g for g in stdout.strip().split() if g]


@dataclass(frozen=True)
class _UserGroups:
    """Outcome of `id -nG <user>`. `exists=False` when user is unknown."""

    exists: bool
    groups: list[str]


def _probe_user_groups(
    pr: ProcessRunner, user: str
) -> _UserGroups | _ProbeError:
    probe = _probe(pr, ("id", "-nG", user))
    if isinstance(probe, _ProbeError):
        return probe
    if probe.exit_code != 0:
        return _UserGroups(exists=False, groups=[])
    return _UserGroups(exists=True, groups=_parse_id_groups(probe.stdout))


def _group_exists_argv(platform: Platform, group: str) -> tuple[str, ...]:
    if platform == "darwin":
        return ("dseditgroup", "-o", "read", group)
    return ("getent", "group", group)


def _probe_group_exists(
    pr: ProcessRunner, platform: Platform, group: str
) -> bool | _ProbeError:
    probe = _probe(pr, _group_exists_argv(platform, group))
    if isinstance(probe, _ProbeError):
        return probe
    return probe.exit_code == 0


def _required_membership_tools(platform: Platform) -> tuple[str, ...]:
    if platform == "darwin":
        return ("id", "dseditgroup")
    return ("id", "getent", "usermod")


def _required_group_create_tool(platform: Platform) -> str:
    return "dseditgroup" if platform == "darwin" else "groupadd"


def _required_rollback_tool(platform: Platform) -> str:
    return "dseditgroup" if platform == "darwin" else "gpasswd"


class EnsureGroupMembershipStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureGroupMembershipParameters,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> EnsureGroupMembershipParameters:
        return self._params

    @override
    def name(self) -> str:
        return (
            f"ensure-group-membership:{self._params.user}:{self._params.group}"
        )

    def _assess_input_issues(self) -> list[str]:
        issues: list[str] = []
        if not _NAME_RE.match(self._params.user):
            issues.append(f"invalid user name: {self._params.user!r}")
        if not _NAME_RE.match(self._params.group):
            issues.append(f"invalid group name: {self._params.group!r}")
        return issues

    def _invalid(self, issues: list[str]) -> StateAssessment:
        return StateAssessment(
            state=ExistingState.INVALID,
            description="cannot ensure group membership",
            issues=issues,
        )

    def _assess_user_groups(self) -> _UserGroups | StateAssessment:
        probed = _probe_user_groups(self._pr, self._params.user)
        if isinstance(probed, _ProbeError):
            return self._invalid([probed.message])
        if not probed.exists:
            return self._invalid([f"user not found: {self._params.user}"])
        return probed

    def _assess_group_for_add(self, platform: Platform) -> StateAssessment | None:
        params = self._params
        group_exists = _probe_group_exists(self._pr, platform, params.group)
        if isinstance(group_exists, _ProbeError):
            return self._invalid([group_exists.message])
        if not group_exists and not params.create_group_if_missing:
            return self._invalid([f"group not found: {params.group}"])
        if not group_exists:
            create_tool = _required_group_create_tool(platform)
            if self._pr.which(create_tool) is None:
                return self._invalid([f"{create_tool} not on PATH"])
        return None

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        platform = self._env.platform()

        issues = self._assess_input_issues()
        if issues:
            return self._invalid(issues)

        for tool in _required_membership_tools(platform):
            if self._pr.which(tool) is None:
                issues.append(f"{tool} not on PATH")
        if issues:
            return self._invalid(issues)

        user_groups = self._assess_user_groups()
        if isinstance(user_groups, StateAssessment):
            return user_groups

        if params.group in user_groups.groups:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"{params.user} is already a member of {params.group}"
                ),
            )

        group_check = self._assess_group_for_add(platform)
        if group_check is not None:
            return group_check

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to add {params.user} to {params.group}",
        )

    def _run_with_code(
        self, argv: tuple[str, ...], code: str
    ) -> tuple[ProcessResult | None, Result | None]:
        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return None, Result.failure(code, str(e))
        except ProcessTimeout as e:
            return None, Result.failure(code, f"timed out: {e}")
        except ProcessDecodeError as e:
            return None, Result.failure(code, f"decode error: {e}")
        except ProcessLaunchError as e:
            return None, Result.failure(code, f"launch error: {e}")
        if result.exit_code != 0:
            return result, Result(
                status=ResultStatus.FAILURE,
                code=code,
                message=f"{argv[0]} exited {result.exit_code}",
                details={
                    "exit_code": str(result.exit_code),
                    "stdout": _truncate(result.stdout),
                    "stderr": _truncate(result.stderr),
                },
            )
        return result, None

    def _create_group_argv(self, platform: Platform) -> tuple[str, ...]:
        if platform == "darwin":
            return ("dseditgroup", "-o", "create", self._params.group)
        return ("groupadd", self._params.group)

    def _add_member_argv(self, platform: Platform) -> tuple[str, ...]:
        params = self._params
        if platform == "darwin":
            return (
                "dseditgroup",
                "-o",
                "edit",
                "-a",
                params.user,
                "-t",
                "user",
                params.group,
            )
        return ("usermod", "-aG", params.group, params.user)

    @override
    def transition(self) -> Result:
        params = self._params
        platform = self._env.platform()

        group_exists = _probe_group_exists(self._pr, platform, params.group)
        if isinstance(group_exists, _ProbeError):
            return Result.failure("MEMBERSHIP_ADD_FAILED", group_exists.message)

        if not group_exists:
            if not params.create_group_if_missing:
                return Result.failure(
                    "GROUP_CREATE_FAILED",
                    f"group not found and create_group_if_missing=False: {params.group}",
                )
            _, failure = self._run_with_code(
                self._create_group_argv(platform), "GROUP_CREATE_FAILED"
            )
            if failure is not None:
                return failure

        add_result, failure = self._run_with_code(
            self._add_member_argv(platform), "MEMBERSHIP_ADD_FAILED"
        )
        if failure is not None:
            return failure
        assert add_result is not None

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=(
                f"added {params.user} to {params.group}"
            ),
            details={
                "exit_code": str(add_result.exit_code),
                "stdout": _truncate(add_result.stdout),
                "stderr": _truncate(add_result.stderr),
            },
        )

    @override
    def rollback(self) -> StateChanger:
        return EnsureGroupMembershipRollbackStateChanger(
            self._params,
            process_runner=self._pr,
            env=self._env,
        )


class EnsureGroupMembershipRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureGroupMembershipParameters,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> EnsureGroupMembershipParameters:
        return self._params

    @override
    def name(self) -> str:
        return (
            f"ensure-group-membership-rollback:"
            f"{self._params.user}:{self._params.group}"
        )

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        platform = self._env.platform()

        issues: list[str] = []
        if not _NAME_RE.match(params.user):
            issues.append(f"invalid user name: {params.user!r}")
        if not _NAME_RE.match(params.group):
            issues.append(f"invalid group name: {params.group!r}")
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back group membership",
                issues=issues,
            )

        if self._pr.which("id") is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back group membership",
                issues=["id not on PATH"],
            )

        user_groups = _probe_user_groups(self._pr, params.user)
        if isinstance(user_groups, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back group membership",
                issues=[user_groups.message],
            )
        if not user_groups.exists:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back group membership",
                issues=[f"user not found: {params.user}"],
            )

        if params.group not in user_groups.groups:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"{params.user} is not a member of {params.group}"
                ),
            )

        required = _required_rollback_tool(platform)
        if self._pr.which(required) is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back group membership",
                issues=[f"{required} not on PATH"],
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=(
                f"ready to remove {params.user} from {params.group}"
            ),
        )

    def _remove_member_argv(self, platform: Platform) -> tuple[str, ...]:
        params = self._params
        if platform == "darwin":
            return (
                "dseditgroup",
                "-o",
                "edit",
                "-d",
                params.user,
                "-t",
                "user",
                params.group,
            )
        return ("gpasswd", "-d", params.user, params.group)

    @override
    def transition(self) -> Result:
        params = self._params
        platform = self._env.platform()

        argv = self._remove_member_argv(platform)
        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return Result.failure("MEMBERSHIP_REMOVE_FAILED", str(e))
        except ProcessTimeout as e:
            return Result.failure(
                "MEMBERSHIP_REMOVE_FAILED", f"timed out: {e}"
            )
        except ProcessDecodeError as e:
            return Result.failure(
                "MEMBERSHIP_REMOVE_FAILED", f"decode error: {e}"
            )
        except ProcessLaunchError as e:
            return Result.failure(
                "MEMBERSHIP_REMOVE_FAILED", f"launch error: {e}"
            )

        details: dict[str, str] = {
            "exit_code": str(result.exit_code),
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
        }
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="MEMBERSHIP_REMOVE_FAILED",
                message=f"{argv[0]} exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"removed {params.user} from {params.group}",
            details=details,
        )
