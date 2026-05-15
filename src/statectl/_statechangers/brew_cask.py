from __future__ import annotations

from dataclasses import dataclass
from typing import override

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealProcessRunner
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


_OUTPUT_CAP: int = 4096
_SHELL_METACHARS: frozenset[str] = frozenset("|&;()<>$`\\\"'\n\r\t *?[]{}!#~")


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


def _has_shell_metachars(name: str) -> bool:
    return any(c in _SHELL_METACHARS for c in name)


def _parse_installed_version(stdout: str) -> str | None:
    """`brew list --cask --versions <name>` prints e.g. `google-chrome 121.0.6167.85`.

    Returns the first version token or None if the output didn't include one.
    """
    line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    parts = line.split()
    if len(parts) < 2:
        return None
    return parts[1]


@dataclass(frozen=True)
class BrewCaskParameters(Parameters):
    name: str
    version: str | None = None
    tap: str | None = None


def _cask_ref(params: BrewCaskParameters) -> str:
    if params.tap:
        return f"{params.tap}/{params.name}"
    return params.name


def _details_from(result: ProcessResult) -> dict[str, str]:
    return {
        "exit_code": str(result.exit_code),
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "duration_ms": str(result.duration_ms),
    }


class BrewCaskStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: BrewCaskParameters,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> BrewCaskParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"brew-cask:{_cask_ref(self._params)}"

    def _query_installed_version(self) -> tuple[str | None, str | None]:
        """Returns (installed_version, error_message).

        - installed_version is the parsed version when brew reports the cask
          as installed, or None when not installed.
        - error_message is set when the query itself failed (process error);
          callers should surface this as an INVALID issue.
        """
        try:
            result = self._pr.run(
                ("brew", "list", "--cask", "--versions", self._params.name),
            )
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ) as e:
            return None, str(e)
        if result.exit_code != 0:
            return None, None
        return _parse_installed_version(result.stdout), None

    def _query_cask_known(self) -> tuple[bool | None, str | None]:
        """Returns (known, error_message). known is None when error."""
        try:
            result = self._pr.run(("brew", "info", "--cask", _cask_ref(self._params)))
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ) as e:
            return None, str(e)
        return result.exit_code == 0, None

    def _preflight_issues(self) -> list[str]:
        issues: list[str] = []
        if _has_shell_metachars(self._params.name):
            issues.append(
                f"name contains shell metacharacters: {self._params.name!r}"
            )
        if self._pr.which("brew") is None:
            issues.append("brew binary not on PATH")
        return issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues: list[str] = self._preflight_issues()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot install cask {params.name}",
                issues=issues,
            )

        installed_version, query_err = self._query_installed_version()
        if query_err is not None:
            issues.append(f"failed to query installed cask: {query_err}")

        if installed_version is None and not issues:
            known, info_err = self._query_cask_known()
            if info_err is not None:
                issues.append(f"failed to query brew info: {info_err}")
            elif known is False:
                issues.append(f"cask not found: {_cask_ref(params)}")

        if (
            installed_version is not None
            and params.version is not None
            and installed_version != params.version
        ):
            issues.append(
                f"installed version {installed_version}, requested {params.version}"
            )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot install cask {params.name}",
                issues=issues,
            )

        if installed_version is not None and (
            params.version is None or installed_version == params.version
        ):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"cask {params.name} already installed "
                    f"(version {installed_version})"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to install cask {_cask_ref(params)}",
        )

    @override
    def transition(self) -> Result:
        ref = _cask_ref(self._params)
        try:
            result = self._pr.run(("brew", "install", "--cask", ref))
        except ProcessNotFound as e:
            return Result.failure("BREW_NOT_FOUND", str(e))
        except ProcessTimeout as e:
            return Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return Result.failure("PROCESS_LAUNCH_ERROR", str(e))

        details = _details_from(result)
        if result.exit_code != 0:
            combined = (result.stdout + "\n" + result.stderr).lower()
            unknown_markers = ("no available cask", "no cask", "cask not found")
            if any(m in combined for m in unknown_markers):
                return Result(
                    status=ResultStatus.FAILURE,
                    code="CASK_NOT_FOUND",
                    message=f"brew reports unknown cask: {ref}",
                    details=details,
                )
            return Result(
                status=ResultStatus.FAILURE,
                code="BREW_CASK_INSTALL_FAILED",
                message=f"brew install --cask exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"installed cask {ref}",
            details=details,
        )

    @override
    def rollback(self) -> StateChanger:
        return BrewCaskRollbackStateChanger(self._params, process_runner=self._pr)


class BrewCaskRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: BrewCaskParameters,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> BrewCaskParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"brew-cask-rollback:{_cask_ref(self._params)}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues: list[str] = []

        if _has_shell_metachars(params.name):
            issues.append(f"name contains shell metacharacters: {params.name!r}")
        if self._pr.which("brew") is None:
            issues.append("brew binary not on PATH")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot uninstall cask {params.name}",
                issues=issues,
            )

        try:
            result = self._pr.run(
                ("brew", "list", "--cask", "--versions", params.name),
            )
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ) as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot uninstall cask {params.name}",
                issues=[f"failed to query installed cask: {e}"],
            )

        if result.exit_code != 0:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"cask {params.name} is not installed",
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to uninstall cask {params.name}",
        )

    @override
    def transition(self) -> Result:
        try:
            result = self._pr.run(("brew", "uninstall", "--cask", self._params.name))
        except ProcessNotFound as e:
            return Result.failure("BREW_NOT_FOUND", str(e))
        except ProcessTimeout as e:
            return Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return Result.failure("PROCESS_LAUNCH_ERROR", str(e))

        details = _details_from(result)
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="BREW_CASK_UNINSTALL_FAILED",
                message=f"brew uninstall --cask exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"uninstalled cask {self._params.name}",
            details=details,
        )
