from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, override

from statectl.interfaces.fs import FileSystem
from statectl.interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessRunner,
    ProcessTimeout,
)
from statectl.modules.fs import RealFileSystem
from statectl.modules.process import RealProcessRunner
from statectl.state_changer import (
    ExistingState,
    Parameters,
    Result,
    ResultStatus,
    StateAssessment,
    StateChanger,
)


_OUTPUT_CAP = 4096


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class RunCommandParameters(Parameters):
    argv: tuple[str, ...]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    creates: Path | None = None
    removes: Path | None = None
    expected_exit_codes: frozenset[int] = field(default_factory=lambda: frozenset({0}))
    timeout: float | None = None


class RunCommandStateChanger(StateChanger):
    def __init__(
        self,
        params: RunCommandParameters,
        process_runner: ProcessRunner | None = None,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        if not self._params.argv:
            return "run-command:<empty>"
        return f"run-command:{self._params.argv[0]}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues: list[str] = []

        if not params.argv:
            issues.append("argv is empty")
        else:
            if self._pr.which(params.argv[0]) is None:
                issues.append(f"executable not found on PATH: {params.argv[0]}")

        if params.cwd is not None:
            if not self._fs.exists(params.cwd):
                issues.append(f"cwd does not exist: {params.cwd}")
            elif not self._fs.is_dir(params.cwd):
                issues.append(f"cwd is not a directory: {params.cwd}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot run command",
                issues=issues,
            )

        if params.creates is not None or params.removes is not None:
            creates_satisfied = (
                params.creates is None or self._fs.exists(params.creates)
            )
            removes_satisfied = (
                params.removes is None or not self._fs.exists(params.removes)
            )
            if creates_satisfied and removes_satisfied:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description="creates/removes hints already satisfied",
                )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to run {' '.join(params.argv)}",
        )

    @override
    def transition(self) -> Result:
        params = self._params
        try:
            result = self._pr.run(
                params.argv,
                cwd=params.cwd,
                env=params.env,
                timeout=params.timeout,
            )
        except ProcessNotFound as e:
            return Result.failure("PROCESS_NOT_FOUND", str(e))
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

        if result.exit_code not in params.expected_exit_codes:
            expected = ",".join(str(c) for c in sorted(params.expected_exit_codes))
            return Result(
                status=ResultStatus.FAILURE,
                code="UNEXPECTED_EXIT",
                message=(
                    f"command exited {result.exit_code}, expected one of {{{expected}}}"
                ),
                details=details,
            )

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"command exited {result.exit_code}",
            details=details,
        )
