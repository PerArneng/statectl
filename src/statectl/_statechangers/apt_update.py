from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import override

from statectl._interfaces.clock import Clock
from statectl._interfaces.env import Env
from statectl._interfaces.fs import FileSystem, FsError
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealClock, RealEnv, RealFileSystem, RealProcessRunner
from statectl._state_changer import (
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
class AptUpdateParameters(Parameters):
    max_age: timedelta = field(default_factory=lambda: timedelta(hours=24))
    lists_dir: Path = Path("/var/lib/apt/lists")
    allow_releaseinfo_change: bool = False


def _newest_release_mtime(
    fs: FileSystem, lists_dir: Path
) -> datetime | None:
    try:
        entries = fs.list_files(lists_dir)
    except FsError:
        return None
    newest: datetime | None = None
    for entry in entries:
        if not entry.is_file:
            continue
        if not (entry.name.endswith("_Release") or entry.name.endswith("_InRelease")):
            continue
        mtime = fs.mtime(entry.path)
        if mtime is None:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


class AptUpdateStateChanger(StateChanger):
    def __init__(
        self,
        params: AptUpdateParameters,
        process_runner: ProcessRunner | None = None,
        file_system: FileSystem | None = None,
        env: Env | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._params = params
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._fs: FileSystem = file_system or RealFileSystem()
        self._env: Env = env or RealEnv()
        self._clock: Clock = clock or RealClock()

    @property
    def params(self) -> AptUpdateParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"apt-update:{self._params.lists_dir}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues: list[str] = []

        if self._env.platform() != "linux":
            issues.append(
                f"platform {self._env.platform()!r} is not Debian-family (linux required)"
            )
        if self._pr.which("apt-get") is None:
            issues.append("apt-get not on PATH")
        if not self._fs.exists(params.lists_dir):
            issues.append(
                f"apt lists directory missing — apt may not be installed: {params.lists_dir}"
            )
        elif not self._fs.is_dir(params.lists_dir):
            issues.append(
                f"apt lists path is not a directory: {params.lists_dir}"
            )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot run apt-get update",
                issues=issues,
            )

        newest = _newest_release_mtime(self._fs, params.lists_dir)
        if newest is not None:
            age = self._clock.now() - newest
            if age <= params.max_age:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=(
                        f"apt lists fresh: age={age} <= max_age={params.max_age}"
                    ),
                )

        return StateAssessment(
            state=ExistingState.READY,
            description="ready to run apt-get update",
        )

    def _build_argv(self) -> tuple[str, ...]:
        argv: list[str] = ["apt-get", "update"]
        if self._params.allow_releaseinfo_change:
            argv.extend(["-o", "Acquire::AllowReleaseInfoChange=true"])
        return tuple(argv)

    @override
    def transition(self) -> Result:
        argv = self._build_argv()
        try:
            result = self._pr.run(argv)
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
            "duration_ms": str(result.duration_ms),
        }

        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="APT_UPDATE_FAILED",
                message=f"apt-get update exited {result.exit_code}",
                details=details,
            )

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message="apt-get update succeeded",
            details=details,
        )
