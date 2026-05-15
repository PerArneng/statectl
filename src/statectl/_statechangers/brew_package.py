from __future__ import annotations

import re
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


_OUTPUT_CAP = 4096
_FORMULA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-@]*$")
_TAP_RE = re.compile(r"^[A-Za-z0-9._\-]+/[A-Za-z0-9._\-]+$")


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class BrewPackageParameters(Parameters):
    name: str
    version: str | None = None
    pin: bool = False
    tap: str | None = None


@dataclass(frozen=True)
class _ProbeError:
    message: str


def _parse_installed_version(formula: str, stdout: str) -> str | None:
    line = stdout.strip()
    if not line:
        return None
    parts = line.split()
    if len(parts) < 2 or parts[0] != formula:
        return None
    return parts[1]


def _is_pinned(formula: str, stdout: str) -> bool:
    return formula in stdout.split()


def _probe(pr: ProcessRunner, argv: tuple[str, ...]) -> ProcessResult | _ProbeError:
    try:
        return pr.run(argv)
    except ProcessNotFound as e:
        return _ProbeError(f"brew probe failed (not found): {e}")
    except ProcessTimeout as e:
        return _ProbeError(f"brew probe timed out: {e}")
    except ProcessDecodeError as e:
        return _ProbeError(f"brew probe decode error: {e}")
    except ProcessLaunchError as e:
        return _ProbeError(f"brew probe launch error: {e}")


class BrewPackageStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: BrewPackageParameters,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> BrewPackageParameters:
        return self._params

    def _install_target(self) -> str:
        params = self._params
        base = f"{params.name}@{params.version}" if params.version else params.name
        return f"{params.tap}/{base}" if params.tap else base

    @override
    def name(self) -> str:
        return f"brew-package:{self._install_target()}"

    def _assess_inputs(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if self._pr.which("brew") is None:
            issues.append("brew binary not on PATH")
        if not _FORMULA_NAME_RE.match(params.name):
            issues.append(f"invalid formula name: {params.name!r}")
        if params.tap is not None and not _TAP_RE.match(params.tap):
            issues.append(f"invalid tap: {params.tap!r}")
        return issues

    def _check_version(
        self, installed_version: str | None
    ) -> str | None:
        version = self._params.version
        if version is None or installed_version == version:
            return None
        return (
            f"installed version {installed_version!r}, requested {version!r}"
        )

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues = self._assess_inputs()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess brew package",
                issues=issues,
            )

        list_probe = _probe(self._pr, ("brew", "list", "--formula", params.name))
        if isinstance(list_probe, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess brew package",
                issues=[list_probe.message],
            )
        installed = list_probe.exit_code == 0
        if not installed:
            return StateAssessment(
                state=ExistingState.READY,
                description=f"ready to install brew formula {self._install_target()}",
            )

        installed_version: str | None = None
        if params.version is not None:
            versions_probe = _probe(
                self._pr, ("brew", "list", "--versions", params.name)
            )
            if isinstance(versions_probe, _ProbeError):
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description="cannot assess brew package",
                    issues=[versions_probe.message],
                )
            installed_version = _parse_installed_version(
                params.name, versions_probe.stdout
            )
            mismatch = self._check_version(installed_version)
            if mismatch is not None:
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description="brew package version mismatch",
                    issues=[mismatch],
                )

        if params.pin:
            pinned_probe = _probe(self._pr, ("brew", "list", "--pinned"))
            if isinstance(pinned_probe, _ProbeError):
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description="cannot assess brew package",
                    issues=[pinned_probe.message],
                )
            if not _is_pinned(params.name, pinned_probe.stdout):
                return StateAssessment(
                    state=ExistingState.READY,
                    description=f"ready to pin brew formula {params.name}",
                )

        return StateAssessment(
            state=ExistingState.ALREADY_APPLIED,
            description=f"brew formula {params.name} already in desired state",
        )

    def _run_brew(
        self, argv: tuple[str, ...], failure_code: str
    ) -> tuple[ProcessResult | None, Result | None]:
        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return None, Result.failure("BREW_NOT_FOUND", str(e))
        except ProcessTimeout as e:
            return None, Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return None, Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return None, Result.failure("PROCESS_LAUNCH_ERROR", str(e))
        if result.exit_code != 0:
            return result, Result(
                status=ResultStatus.FAILURE,
                code=failure_code,
                message=f"{' '.join(argv)} exited {result.exit_code}",
                details={
                    "exit_code": str(result.exit_code),
                    "stdout": _truncate(result.stdout),
                    "stderr": _truncate(result.stderr),
                },
            )
        return result, None

    @override
    def transition(self) -> Result:
        params = self._params

        install_result, install_failure = self._run_brew(
            ("brew", "install", self._install_target()),
            failure_code="BREW_INSTALL_FAILED",
        )
        if install_failure is not None:
            return install_failure
        assert install_result is not None
        details: dict[str, str] = {
            "install_exit_code": str(install_result.exit_code),
            "install_stdout": _truncate(install_result.stdout),
            "install_stderr": _truncate(install_result.stderr),
        }

        if params.pin:
            pin_result, pin_failure = self._run_brew(
                ("brew", "pin", params.name), failure_code="BREW_PIN_FAILED"
            )
            if pin_failure is not None:
                merged = dict(pin_failure.details)
                merged.update(details)
                return Result(
                    status=pin_failure.status,
                    code=pin_failure.code,
                    message=pin_failure.message,
                    details=merged,
                )
            assert pin_result is not None
            details["pin_exit_code"] = str(pin_result.exit_code)
            details["pin_stdout"] = _truncate(pin_result.stdout)
            details["pin_stderr"] = _truncate(pin_result.stderr)

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"installed brew formula {self._install_target()}",
            details=details,
        )

    @override
    def rollback(self) -> StateChanger:
        return BrewPackageRollbackStateChanger(
            self._params, process_runner=self._pr
        )


class BrewPackageRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: BrewPackageParameters,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> BrewPackageParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"brew-package-rollback:{self._params.name}"

    def _assess_inputs(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if self._pr.which("brew") is None:
            issues.append("brew binary not on PATH")
        if not _FORMULA_NAME_RE.match(params.name):
            issues.append(f"invalid formula name: {params.name!r}")
        return issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues = self._assess_inputs()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess brew package rollback",
                issues=issues,
            )

        list_probe = _probe(self._pr, ("brew", "list", "--formula", params.name))
        if isinstance(list_probe, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess brew package rollback",
                issues=[list_probe.message],
            )
        if list_probe.exit_code != 0:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"brew formula {params.name} already not installed",
            )

        pinned_probe = _probe(self._pr, ("brew", "list", "--pinned"))
        if isinstance(pinned_probe, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess brew package rollback",
                issues=[pinned_probe.message],
            )
        if _is_pinned(params.name, pinned_probe.stdout):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"refusing to uninstall pinned formula {params.name}",
                issues=[
                    f"formula {params.name} is pinned; unpin explicitly before rollback"
                ],
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to uninstall brew formula {params.name}",
        )

    @override
    def transition(self) -> Result:
        params = self._params
        try:
            result = self._pr.run(("brew", "uninstall", params.name))
        except ProcessNotFound as e:
            return Result.failure("BREW_NOT_FOUND", str(e))
        except ProcessTimeout as e:
            return Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return Result.failure("PROCESS_LAUNCH_ERROR", str(e))

        details: dict[str, str] = {
            "exit_code": str(result.exit_code),
            "stdout": _truncate(result.stdout),
            "stderr": _truncate(result.stderr),
        }
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="BREW_UNINSTALL_FAILED",
                message=f"brew uninstall exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"uninstalled brew formula {params.name}",
            details=details,
        )
