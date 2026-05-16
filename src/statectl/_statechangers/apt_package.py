from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl._interfaces.fs import FileSystem
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealFileSystem, RealProcessRunner
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
_DEBIAN_MARKER = Path("/etc/debian_version")
_APT_BINARIES: tuple[str, ...] = ("apt-get", "dpkg", "apt-mark", "apt-cache")
_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+\-.]*$")
_APT_ENV = {"DEBIAN_FRONTEND": "noninteractive"}


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class AptPackageParameters(Parameters):
    name: str
    version: str | None = None
    hold: bool = False
    allow_downgrade: bool = False


@dataclass(frozen=True)
class _ProbeError:
    message: str


def _probe(
    pr: ProcessRunner, argv: tuple[str, ...]
) -> ProcessResult | _ProbeError:
    try:
        return pr.run(argv)
    except ProcessNotFound as e:
        return _ProbeError(f"apt probe failed (not found): {e}")
    except ProcessTimeout as e:
        return _ProbeError(f"apt probe timed out: {e}")
    except ProcessDecodeError as e:
        return _ProbeError(f"apt probe decode error: {e}")
    except ProcessLaunchError as e:
        return _ProbeError(f"apt probe launch error: {e}")


def _parse_dpkg_query_version(stdout: str) -> str | None:
    text = stdout.strip()
    return text or None


def _madison_has_version(stdout: str, name: str, version: str) -> bool:
    for raw in stdout.splitlines():
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) >= 2 and parts[0] == name and parts[1] == version:
            return True
    return False


def _is_held(stdout: str, name: str) -> bool:
    return any(line.strip() == name for line in stdout.splitlines())


class AptPackageStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: AptPackageParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> AptPackageParameters:
        return self._params

    def _install_target(self) -> str:
        params = self._params
        if params.version is not None:
            return f"{params.name}={params.version}"
        return params.name

    @override
    def name(self) -> str:
        return f"apt-package:{self._install_target()}"

    def _assess_inputs(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if not self._fs.is_file(_DEBIAN_MARKER):
            issues.append(
                "platform is not Debian-family Linux (/etc/debian_version absent)"
            )
        for binary in _APT_BINARIES:
            if self._pr.which(binary) is None:
                issues.append(f"{binary} binary not on PATH")
        if not _PACKAGE_NAME_RE.match(params.name):
            issues.append(f"invalid package name: {params.name!r}")
        return issues

    def _assess_installed_version(
        self, installed: bool, issues: list[str]
    ) -> str | None:
        params = self._params
        if not installed or params.version is None:
            return None
        probe = _probe(
            self._pr,
            ("dpkg-query", "-W", "-f=${Version}", params.name),
        )
        if isinstance(probe, _ProbeError):
            issues.append(probe.message)
            return None
        return _parse_dpkg_query_version(probe.stdout)

    def _assess_downgrade(
        self, installed_version: str | None, issues: list[str]
    ) -> None:
        params = self._params
        if (
            params.version is None
            or installed_version is None
            or installed_version == params.version
            or params.allow_downgrade
        ):
            return
        compare = _probe(
            self._pr,
            (
                "dpkg",
                "--compare-versions",
                installed_version,
                "gt",
                params.version,
            ),
        )
        if isinstance(compare, _ProbeError):
            issues.append(compare.message)
            return
        if compare.exit_code == 0:
            issues.append(
                f"would require downgrade: installed {installed_version!r} > "
                f"requested {params.version!r}"
            )

    def _assess_apt_cache(self, issues: list[str]) -> None:
        params = self._params
        if params.version is None:
            return
        probe = _probe(
            self._pr, ("apt-cache", "madison", params.name)
        )
        if isinstance(probe, _ProbeError):
            issues.append(probe.message)
            return
        if probe.exit_code != 0 or not _madison_has_version(
            probe.stdout, params.name, params.version
        ):
            issues.append(
                f"{params.name}={params.version} not found in apt cache"
            )

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues = self._assess_inputs()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess apt package",
                issues=issues,
            )

        status_probe = _probe(self._pr, ("dpkg", "-s", params.name))
        if isinstance(status_probe, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess apt package",
                issues=[status_probe.message],
            )
        installed = status_probe.exit_code == 0

        installed_version = self._assess_installed_version(installed, issues)
        self._assess_downgrade(installed_version, issues)
        self._assess_apt_cache(issues)

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess apt package",
                issues=issues,
            )

        held: bool = False
        if params.hold or installed:
            hold_probe = _probe(self._pr, ("apt-mark", "showhold"))
            if isinstance(hold_probe, _ProbeError):
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description="cannot assess apt package",
                    issues=[hold_probe.message],
                )
            held = _is_held(hold_probe.stdout, params.name)

        version_ok = params.version is None or installed_version == params.version
        hold_ok = (not params.hold) or held
        if installed and version_ok and hold_ok:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"apt package {self._install_target()} already in desired state",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to install apt package {self._install_target()}",
        )

    def _run_apt(
        self,
        argv: tuple[str, ...],
        not_found_code: str,
        failure_code: str,
    ) -> tuple[ProcessResult | None, Result | None]:
        try:
            result = self._pr.run(argv, env=_APT_ENV)
        except ProcessNotFound as e:
            return None, Result.failure(not_found_code, str(e))
        except ProcessTimeout as e:
            return None, Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return None, Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return None, Result.failure("PROCESS_LAUNCH_ERROR", str(e))
        if result.exit_code != 0:
            code = failure_code
            if _is_package_not_found(result.stderr):
                code = "PACKAGE_NOT_FOUND"
            return result, Result(
                status=ResultStatus.FAILURE,
                code=code,
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

        install_result, install_failure = self._run_apt(
            ("apt-get", "-y", "install", self._install_target()),
            not_found_code="APT_NOT_FOUND",
            failure_code="APT_INSTALL_FAILED",
        )
        if install_failure is not None:
            return install_failure
        assert install_result is not None
        details: dict[str, str] = {
            "install_exit_code": str(install_result.exit_code),
            "install_stdout": _truncate(install_result.stdout),
            "install_stderr": _truncate(install_result.stderr),
        }

        if params.hold:
            hold_result, hold_failure = self._run_apt(
                ("apt-mark", "hold", params.name),
                not_found_code="APT_NOT_FOUND",
                failure_code="APT_HOLD_FAILED",
            )
            if hold_failure is not None:
                merged = dict(hold_failure.details)
                merged.update(details)
                return Result(
                    status=hold_failure.status,
                    code=hold_failure.code,
                    message=hold_failure.message,
                    details=merged,
                )
            assert hold_result is not None
            details["hold_exit_code"] = str(hold_result.exit_code)
            details["hold_stdout"] = _truncate(hold_result.stdout)
            details["hold_stderr"] = _truncate(hold_result.stderr)

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"installed apt package {self._install_target()}",
            details=details,
        )

    @override
    def rollback(self) -> StateChanger:
        return AptPackageRollbackStateChanger(
            self._params, file_system=self._fs, process_runner=self._pr
        )


def _is_package_not_found(stderr: str) -> bool:
    lowered = stderr.lower()
    return (
        "unable to locate package" in lowered
        or "has no installation candidate" in lowered
    )


class AptPackageRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: AptPackageParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> AptPackageParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"apt-package-rollback:{self._params.name}"

    def _assess_inputs(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if not self._fs.is_file(_DEBIAN_MARKER):
            issues.append(
                "platform is not Debian-family Linux (/etc/debian_version absent)"
            )
        for binary in ("apt-get", "dpkg", "apt-mark"):
            if self._pr.which(binary) is None:
                issues.append(f"{binary} binary not on PATH")
        if not _PACKAGE_NAME_RE.match(params.name):
            issues.append(f"invalid package name: {params.name!r}")
        return issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues = self._assess_inputs()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess apt package rollback",
                issues=issues,
            )

        status_probe = _probe(self._pr, ("dpkg", "-s", params.name))
        if isinstance(status_probe, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess apt package rollback",
                issues=[status_probe.message],
            )
        if status_probe.exit_code != 0:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"apt package {params.name} already not installed",
            )

        hold_probe = _probe(self._pr, ("apt-mark", "showhold"))
        if isinstance(hold_probe, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot assess apt package rollback",
                issues=[hold_probe.message],
            )
        if _is_held(hold_probe.stdout, params.name):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"refusing to uninstall held package {params.name}",
                issues=[
                    f"package {params.name} is held; unhold explicitly before rollback"
                ],
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove apt package {params.name}",
        )

    @override
    def transition(self) -> Result:
        params = self._params
        try:
            result = self._pr.run(
                ("apt-get", "-y", "remove", params.name), env=_APT_ENV
            )
        except ProcessNotFound as e:
            return Result.failure("APT_NOT_FOUND", str(e))
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
                code="APT_REMOVE_FAILED",
                message=f"apt-get remove exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"removed apt package {params.name}",
            details=details,
        )
