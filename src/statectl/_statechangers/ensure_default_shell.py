from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl._interfaces.env import Env, Platform
from statectl._interfaces.fs import FileSystem, FsError, FsNotFound
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
_SHELL_PATH_RE = re.compile(r"^/[A-Za-z0-9._+/@\-]+$")
_USER_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._\-]*\$?$")
_ETC_SHELLS = Path("/etc/shells")


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class EnsureDefaultShellParameters(Parameters):
    user: str
    shell: Path
    register_in_etc_shells: bool = False


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


def _parse_getent_shell(stdout: str) -> Path | None:
    # `getent passwd <user>` returns exactly one row, so taking [0] is safe.
    line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    if not line:
        return None
    parts = line.split(":")
    if len(parts) < 7:
        return None
    return Path(parts[6])


def _parse_dscl_shell(stdout: str) -> Path | None:
    for raw in stdout.splitlines():
        text = raw.strip()
        if text.startswith("UserShell:"):
            value = text.split(":", 1)[1].strip()
            if value:
                return Path(value)
    return None


def _current_shell_argv(platform: Platform, user: str) -> tuple[str, ...]:
    if platform == "darwin":
        return ("dscl", ".", "-read", f"/Users/{user}", "UserShell")
    return ("getent", "passwd", user)


def _required_chsh_tool(platform: Platform) -> str:
    return "dscl" if platform == "darwin" else "chsh"


def _parse_current_shell(platform: Platform, stdout: str) -> Path | None:
    if platform == "darwin":
        return _parse_dscl_shell(stdout)
    return _parse_getent_shell(stdout)


def _shell_listed_in_etc_shells(fs: FileSystem, shell: Path) -> bool | None:
    """Returns True/False, or None if /etc/shells cannot be read."""
    if not fs.exists(_ETC_SHELLS):
        return False
    try:
        contents = fs.read_text_file(_ETC_SHELLS)
    except FsError:
        return None
    target = str(shell)
    for raw in contents.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == target:
            return True
    return False


def _probe_current_shell(
    pr: ProcessRunner, platform: Platform, user: str
) -> Path | None | _ProbeError:
    """Returns the user's current login shell, None if user not found, or
    _ProbeError on probe failure."""
    probe = _probe(pr, _current_shell_argv(platform, user))
    if isinstance(probe, _ProbeError):
        return probe
    if probe.exit_code != 0:
        return None
    return _parse_current_shell(platform, probe.stdout)


class EnsureDefaultShellStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureDefaultShellParameters,
        process_runner: ProcessRunner | None = None,
        file_system: FileSystem | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._fs: FileSystem = file_system or RealFileSystem()
        self._env: Env = env or RealEnv()
        self._pre_shell: Path | None = None

    @property
    def params(self) -> EnsureDefaultShellParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-default-shell:{self._params.user}:{self._params.shell}"

    def _assess_input_issues(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if not _USER_NAME_RE.match(params.user):
            issues.append(f"invalid user name: {params.user!r}")
        if not params.shell.is_absolute() or not _SHELL_PATH_RE.match(str(params.shell)):
            issues.append(f"shell path contains invalid characters: {params.shell}")
        return issues

    def _assess_shell_file(self) -> list[str]:
        shell = self._params.shell
        issues: list[str] = []
        if not self._fs.exists(shell):
            issues.append(f"shell does not exist: {shell}")
            return issues
        if not self._fs.is_file(shell):
            issues.append(f"shell is not a regular file: {shell}")
            return issues
        mode = self._fs.stat_mode(shell)
        if mode is None or not bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            issues.append(f"shell is not executable: {shell}")
        return issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        platform = self._env.platform()

        issues = self._assess_input_issues()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure default shell",
                issues=issues,
            )

        current = _probe_current_shell(self._pr, platform, params.user)
        if isinstance(current, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure default shell",
                issues=[current.message],
            )
        if current is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure default shell",
                issues=[f"user does not exist: {params.user}"],
            )

        if current == params.shell:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"login shell for {params.user} already {params.shell}"
                ),
            )

        action_issues: list[str] = []
        action_issues.extend(self._assess_shell_file())

        listed = _shell_listed_in_etc_shells(self._fs, params.shell)
        if listed is None:
            action_issues.append(f"cannot read {_ETC_SHELLS}")
        elif not listed and not params.register_in_etc_shells:
            action_issues.append(
                f"shell not in {_ETC_SHELLS}: {params.shell} "
                f"(set register_in_etc_shells=True to allow appending)"
            )

        required = _required_chsh_tool(platform)
        if self._pr.which(required) is None:
            action_issues.append(f"{required} not on PATH")

        if action_issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure default shell",
                issues=action_issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=(
                f"ready to set login shell for {params.user} to {params.shell}"
            ),
        )

    def _maybe_register_in_etc_shells(self) -> Result | None:
        params = self._params
        if not params.register_in_etc_shells:
            return None
        listed = _shell_listed_in_etc_shells(self._fs, params.shell)
        if listed is None:
            return Result.failure(
                "ETC_SHELLS_WRITE_FAILED",
                f"cannot read {_ETC_SHELLS} to determine whether to append",
            )
        if listed:
            return None
        try:
            existing = (
                self._fs.read_text_file(_ETC_SHELLS)
                if self._fs.exists(_ETC_SHELLS)
                else ""
            )
        except FsError as e:
            return Result.failure(
                "ETC_SHELLS_WRITE_FAILED",
                f"failed to read {_ETC_SHELLS}: {e}",
            )
        prefix = "" if existing.endswith("\n") or existing == "" else "\n"
        try:
            self._fs.write_text_file(
                _ETC_SHELLS, f"{existing}{prefix}{params.shell}\n"
            )
        except FsError as e:
            return Result.failure(
                "ETC_SHELLS_WRITE_FAILED",
                f"failed to append shell to {_ETC_SHELLS}: {e}",
            )
        return None

    def _set_login_shell(
        self, platform: Platform, pre_shell: Path
    ) -> tuple[ProcessResult | None, Result | None]:
        """Run the platform-specific shell-change command (`chsh` on linux,
        `dscl . -change` on darwin). The umbrella failure code is
        `CHSH_FAILED` regardless of platform — kept stable for callers."""
        params = self._params
        if platform == "darwin":
            argv: tuple[str, ...] = (
                "dscl",
                ".",
                "-change",
                f"/Users/{params.user}",
                "UserShell",
                str(pre_shell),
                str(params.shell),
            )
        else:
            argv = ("chsh", "-s", str(params.shell), params.user)
        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return None, Result.failure("CHSH_FAILED", str(e))
        except ProcessTimeout as e:
            return None, Result.failure("CHSH_FAILED", f"timed out: {e}")
        except ProcessDecodeError as e:
            return None, Result.failure("CHSH_FAILED", f"decode error: {e}")
        except ProcessLaunchError as e:
            return None, Result.failure("CHSH_FAILED", f"launch error: {e}")
        if result.exit_code != 0:
            return result, Result(
                status=ResultStatus.FAILURE,
                code="CHSH_FAILED",
                message=f"{argv[0]} exited {result.exit_code}",
                details={
                    "exit_code": str(result.exit_code),
                    "stdout": _truncate(result.stdout),
                    "stderr": _truncate(result.stderr),
                    "pre_shell": str(pre_shell),
                },
            )
        return result, None

    @override
    def transition(self) -> Result:
        params = self._params
        platform = self._env.platform()

        if not self._fs.is_file(params.shell):
            return Result.failure(
                "SHELL_VANISHED",
                f"shell binary missing at transition time: {params.shell}",
            )

        register_failure = self._maybe_register_in_etc_shells()
        if register_failure is not None:
            return register_failure

        current = _probe_current_shell(self._pr, platform, params.user)
        if isinstance(current, _ProbeError) or current is None:
            message = (
                current.message
                if isinstance(current, _ProbeError)
                else f"user not found: {params.user}"
            )
            return Result.failure("CHSH_FAILED", message)

        run_result, failure = self._set_login_shell(platform, current)
        if failure is not None:
            return failure
        assert run_result is not None

        self._pre_shell = current
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=(
                f"set login shell for {params.user} to {params.shell} "
                f"(was {current})"
            ),
            details={
                "exit_code": str(run_result.exit_code),
                "stdout": _truncate(run_result.stdout),
                "stderr": _truncate(run_result.stderr),
                "pre_shell": str(current),
            },
        )

    @override
    def rollback(self) -> StateChanger:
        return EnsureDefaultShellRollbackStateChanger(
            self._params,
            pre_shell=self._pre_shell,
            process_runner=self._pr,
            file_system=self._fs,
            env=self._env,
        )


class EnsureDefaultShellRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureDefaultShellParameters,
        pre_shell: Path | None = None,
        process_runner: ProcessRunner | None = None,
        file_system: FileSystem | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._pre_shell = pre_shell
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._fs: FileSystem = file_system or RealFileSystem()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> EnsureDefaultShellParameters:
        return self._params

    @property
    def pre_shell(self) -> Path | None:
        return self._pre_shell

    @override
    def name(self) -> str:
        return f"ensure-default-shell-rollback:{self._params.user}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        platform = self._env.platform()

        if self._pre_shell is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back default shell",
                issues=[
                    "pre_shell is unknown; forward transition did not run"
                ],
            )

        if not _USER_NAME_RE.match(params.user):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back default shell",
                issues=[f"invalid user name: {params.user!r}"],
            )

        current = _probe_current_shell(self._pr, platform, params.user)
        if isinstance(current, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back default shell",
                issues=[current.message],
            )
        if current is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back default shell",
                issues=[f"user does not exist: {params.user}"],
            )

        if current == self._pre_shell:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"login shell for {params.user} already {self._pre_shell}"
                ),
            )

        issues: list[str] = []
        if not self._fs.is_file(self._pre_shell):
            issues.append(
                f"prior shell missing or not a regular file: {self._pre_shell}"
            )
        required = _required_chsh_tool(platform)
        if self._pr.which(required) is None:
            issues.append(f"{required} not on PATH")
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back default shell",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=(
                f"ready to restore login shell for {params.user} "
                f"to {self._pre_shell}"
            ),
        )

    @override
    def transition(self) -> Result:
        params = self._params
        platform = self._env.platform()
        if self._pre_shell is None:
            return Result.failure(
                "CHSH_FAILED", "pre_shell is unknown; cannot roll back"
            )

        current = _probe_current_shell(self._pr, platform, params.user)
        if isinstance(current, _ProbeError) or current is None:
            message = (
                current.message
                if isinstance(current, _ProbeError)
                else f"user not found: {params.user}"
            )
            return Result.failure("CHSH_FAILED", message)

        if current == self._pre_shell:
            return Result(
                status=ResultStatus.SUCCESS,
                code="OK",
                message=(
                    f"login shell for {params.user} already "
                    f"{self._pre_shell}; nothing to roll back"
                ),
                details={"pre_shell": str(self._pre_shell)},
            )

        if platform == "darwin":
            argv: tuple[str, ...] = (
                "dscl",
                ".",
                "-change",
                f"/Users/{params.user}",
                "UserShell",
                str(current),
                str(self._pre_shell),
            )
        else:
            argv = ("chsh", "-s", str(self._pre_shell), params.user)

        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return Result.failure("CHSH_FAILED", str(e))
        except ProcessTimeout as e:
            return Result.failure("CHSH_FAILED", f"timed out: {e}")
        except ProcessDecodeError as e:
            return Result.failure("CHSH_FAILED", f"decode error: {e}")
        except ProcessLaunchError as e:
            return Result.failure("CHSH_FAILED", f"launch error: {e}")

        details: dict[str, str] = {
            "exit_code": str(result.exit_code),
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
            "pre_shell": str(self._pre_shell),
        }
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="CHSH_FAILED",
                message=f"{argv[0]} exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=(
                f"restored login shell for {params.user} to {self._pre_shell}"
            ),
            details=details,
        )
