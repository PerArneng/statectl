from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import override

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessError,
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


_TAP_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")
_OUTPUT_CAP: int = 4096


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class BrewTapParameters(Parameters):
    name: str
    url: str | None = None


def _parse_tap_list(stdout: str) -> set[str]:
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _precheck(
    pr: ProcessRunner, params: BrewTapParameters, action_label: str
) -> StateAssessment | None:
    issues: list[str] = []
    if not _TAP_NAME_PATTERN.match(params.name):
        issues.append(f"invalid tap name: {params.name}")
    if pr.which("brew") is None:
        issues.append("brew binary not on PATH")
    if issues:
        return StateAssessment(
            state=ExistingState.INVALID,
            description=action_label,
            issues=issues,
        )
    return None


def _invalid(description: str, issue: str) -> StateAssessment:
    return StateAssessment(
        state=ExistingState.INVALID, description=description, issues=[issue]
    )


def _run_safely_on(
    pr: ProcessRunner, argv: tuple[str, ...]
) -> ProcessResult | str:
    """Run a brew query in assess. Returns the ProcessResult on success
    or a human-readable error string. assess must never raise."""
    try:
        return pr.run(argv)
    except ProcessNotFound as e:
        return f"brew not found while running {' '.join(argv)}: {e}"
    except ProcessTimeout as e:
        return f"brew timed out while running {' '.join(argv)}: {e}"
    except ProcessDecodeError as e:
        return f"brew output decode error: {e}"
    except ProcessLaunchError as e:
        return f"brew launch error: {e}"
    except ProcessError as e:
        return f"brew error: {e}"


def _query_tap_list(
    pr: ProcessRunner, params: BrewTapParameters, kind: str
) -> StateAssessment | set[str]:
    desc = f"cannot list taps for {params.name}"
    result = _run_safely_on(pr, ("brew", "tap"))
    if isinstance(result, str):
        return _invalid(desc, result)
    if result.exit_code != 0:
        return _invalid(
            desc,
            f"`brew tap` exited {result.exit_code}: {_truncate(result.stderr)}",
        )
    return _parse_tap_list(result.stdout)


def _query_tap_info(
    pr: ProcessRunner, params: BrewTapParameters
) -> StateAssessment | dict[str, object]:
    desc = f"cannot inspect tap {params.name}"
    result = _run_safely_on(pr, ("brew", "tap-info", "--json=v1", params.name))
    if isinstance(result, str):
        return _invalid(desc, result)
    if result.exit_code != 0:
        return _invalid(
            desc,
            f"`brew tap-info` exited {result.exit_code}: {_truncate(result.stderr)}",
        )
    info = _parse_tap_info(result.stdout)
    if info is None:
        return _invalid(
            f"cannot parse tap-info for {params.name}",
            f"could not parse tap-info JSON: {_truncate(result.stdout)}",
        )
    return info


def _parse_tap_info(stdout: str) -> dict[str, object] | None:
    """Parse `brew tap-info --json=v1 <name>` output. Returns the first record
    or None if the output is empty/malformed/not-an-array."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    return first


class BrewTapStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: BrewTapParameters,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> BrewTapParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"brew-tap:{self._params.name}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        precheck = _precheck(self._pr, params, action_label=f"cannot tap {params.name}")
        if precheck is not None:
            return precheck

        taps_or_invalid = _query_tap_list(self._pr, params, kind="tap")
        if isinstance(taps_or_invalid, StateAssessment):
            return taps_or_invalid
        if params.name not in taps_or_invalid:
            return StateAssessment(
                state=ExistingState.READY,
                description=f"ready to tap {params.name}",
            )

        if params.url is None:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"tap already configured: {params.name}",
            )

        info_or_invalid = _query_tap_info(self._pr, params)
        if isinstance(info_or_invalid, StateAssessment):
            return info_or_invalid

        remote = info_or_invalid.get("remote")
        if remote != params.url:
            return _invalid(
                f"tap exists with different URL: {params.name}",
                f"tap {params.name} is configured with remote {remote!r}, "
                f"expected {params.url!r}",
            )

        return StateAssessment(
            state=ExistingState.ALREADY_APPLIED,
            description=f"tap already configured with matching URL: {params.name}",
        )

    def _build_tap_argv(self) -> tuple[str, ...]:
        if self._params.url is None:
            return ("brew", "tap", self._params.name)
        return ("brew", "tap", self._params.name, self._params.url)

    @override
    def transition(self) -> Result:
        argv = self._build_tap_argv()
        try:
            result = self._pr.run(argv)
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
            "duration_ms": str(result.duration_ms),
        }
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="BREW_TAP_FAILED",
                message=f"`brew tap` exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"tapped {self._params.name}",
            details=details,
        )

    @override
    def rollback(self) -> StateChanger:
        return BrewTapRollbackStateChanger(self._params, process_runner=self._pr)


class BrewTapRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: BrewTapParameters,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @override
    def name(self) -> str:
        return f"brew-tap-rollback:{self._params.name}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        precheck = _precheck(
            self._pr, params, action_label=f"cannot untap {params.name}"
        )
        if precheck is not None:
            return precheck

        taps_or_invalid = _query_tap_list(self._pr, params, kind="untap")
        if isinstance(taps_or_invalid, StateAssessment):
            return taps_or_invalid
        if params.name not in taps_or_invalid:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {params.name} is not tapped",
            )

        info_or_invalid = _query_tap_info(self._pr, params)
        if isinstance(info_or_invalid, StateAssessment):
            return info_or_invalid

        installed = info_or_invalid.get("installed")
        if isinstance(installed, list) and installed:
            installed_names = [
                item.get("name") if isinstance(item, dict) else str(item)
                for item in installed
            ]
            return _invalid(
                f"refusing to untap {params.name}: installed formulae depend on it",
                f"installed formulae from {params.name} would break: {installed_names}",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to untap {params.name}",
        )

    @override
    def transition(self) -> Result:
        argv = ("brew", "untap", self._params.name)
        try:
            result = self._pr.run(argv)
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
            "duration_ms": str(result.duration_ms),
        }
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="BREW_UNTAP_FAILED",
                message=f"`brew untap` exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"untapped {self._params.name}",
            details=details,
        )
