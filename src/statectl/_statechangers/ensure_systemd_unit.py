from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, override

from statectl._interfaces.env import Env
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


SystemdScope = Literal["system", "user"]


_USER_UNIT_REL: str = ".config/systemd/user"
_SYSTEM_UNIT_DIR: Path = Path("/etc/systemd/system")
_OUTPUT_CAP: int = 4096
_KNOWN_SUFFIXES: tuple[str, ...] = (
    ".service",
    ".timer",
    ".socket",
    ".target",
    ".mount",
    ".automount",
    ".path",
    ".swap",
    ".slice",
    ".scope",
)
_PROCESS_ERRORS: tuple[type[Exception], ...] = (
    ProcessNotFound,
    ProcessTimeout,
    ProcessDecodeError,
    ProcessLaunchError,
)


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


def _details_from(result: ProcessResult) -> dict[str, str]:
    return {
        "exit_code": str(result.exit_code),
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "duration_ms": str(result.duration_ms),
    }


def _has_section_header(content: str) -> bool:
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]") and len(line) >= 3:
            return True
    return False


def _extract_description(content: str) -> str | None:
    in_unit_section = False
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_unit_section = line == "[Unit]"
            continue
        if in_unit_section and line.startswith("Description="):
            return line[len("Description=") :].strip()
    return None


@dataclass(frozen=True)
class _UnitPaths:
    """Where the unit file lives on disk, computed once from parameters + env."""

    unit_dir: Path
    unit_path: Path

    @classmethod
    def build(
        cls,
        params: "EnsureSystemdUnitParameters",
        env: Env,
    ) -> "_UnitPaths":
        if params.scope == "system":
            unit_dir = _SYSTEM_UNIT_DIR
        else:
            unit_dir = env.user_home() / _USER_UNIT_REL
        return cls(unit_dir=unit_dir, unit_path=unit_dir / params.unit_name)


def _systemctl_argv(scope: SystemdScope, *rest: str) -> tuple[str, ...]:
    if scope == "user":
        return ("systemctl", "--user", *rest)
    return ("systemctl", *rest)


def _query_systemctl(
    pr: ProcessRunner, scope: SystemdScope, verb: str, unit_name: str
) -> str | None:
    """Run a non-mutating systemctl query like `is-enabled` / `is-active`.
    Returns the trimmed stdout (one word state name) or None on launch failure.
    Both exit zero and exit non-zero map to whatever stdout was printed —
    systemctl prints the state on stderr for some cases but stdout in modern
    versions; we read stdout first, falling back to stderr.
    """
    try:
        result = pr.run(_systemctl_argv(scope, verb, unit_name))
    except _PROCESS_ERRORS:
        return None
    text = result.stdout.strip() or result.stderr.strip()
    return text or None


def _enable_state_matches(state: str | None, want_enabled: bool) -> bool:
    if state is None:
        return False
    if want_enabled:
        return state == "enabled"
    return state in ("disabled", "static")


def _active_state_matches(state: str | None, want_started: bool) -> bool:
    if state is None:
        return False
    if want_started:
        return state == "active"
    return state == "inactive"


@dataclass(frozen=True)
class EnsureSystemdUnitParameters(Parameters):
    unit_name: str
    unit_content: str
    scope: SystemdScope
    enabled: bool = True
    started: bool = True
    reload_on_change: bool = True


class EnsureSystemdUnitStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureSystemdUnitParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()
        self._paths: _UnitPaths = _UnitPaths.build(params, self._env)

    @property
    def params(self) -> EnsureSystemdUnitParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-systemd-unit:{self._params.unit_name}"

    def _preflight_issues(self) -> list[str]:
        params = self._params
        issues: list[str] = []

        if self._env.platform() != "linux":
            issues.append("systemd is Linux-only (platform is not linux)")

        if self._pr.which("systemctl") is None:
            issues.append("systemctl not on PATH")

        if not params.unit_name:
            issues.append("unit_name is empty")
        else:
            if "/" in params.unit_name or "\0" in params.unit_name:
                issues.append(
                    f"unit_name must not contain path separators or NUL: "
                    f"{params.unit_name!r}"
                )
            if not any(params.unit_name.endswith(s) for s in _KNOWN_SUFFIXES):
                issues.append(
                    f"unit suffix unrecognised: {params.unit_name!r} "
                    f"(known suffixes: {', '.join(_KNOWN_SUFFIXES)})"
                )

        if not _has_section_header(params.unit_content):
            issues.append(
                "unit_content does not look like a valid unit file: "
                "no [Section] header found"
            )

        return issues

    def _existing_unit_issues(self, unit_path: Path) -> list[str]:
        params = self._params
        issues: list[str] = []
        if not self._fs.is_file(unit_path):
            issues.append(
                f"unit path exists but is not a regular file: {unit_path}"
            )
            return issues
        try:
            existing = self._fs.read_text_file(unit_path)
        except FsError as e:
            issues.append(f"cannot read existing unit at {unit_path}: {e}")
            return issues
        if existing == params.unit_content:
            return issues
        existing_desc = _extract_description(existing)
        new_desc = _extract_description(params.unit_content)
        if (
            existing_desc is not None
            and new_desc is not None
            and existing_desc != new_desc
        ):
            issues.append(
                f"unit at {unit_path} has different [Unit] Description= "
                f"({existing_desc!r} vs {new_desc!r}); refusing to overwrite "
                f"a unit we don't own"
            )
        return issues

    def _unit_dir_issues(self, unit_dir: Path) -> list[str]:
        if not self._fs.exists(unit_dir):
            return [f"unit directory does not exist: {unit_dir}"]
        if not self._fs.is_dir(unit_dir):
            return [f"unit directory is not a directory: {unit_dir}"]
        if not self._fs.is_writable(unit_dir):
            return [f"unit directory is not writable: {unit_dir}"]
        return []

    def _unit_matches_on_disk(self, unit_path: Path) -> bool:
        if not self._fs.is_file(unit_path):
            return False
        try:
            existing = self._fs.read_text_file(unit_path)
        except FsError:
            return False
        return existing == self._params.unit_content

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        unit_dir = self._paths.unit_dir
        unit_path = self._paths.unit_path

        issues: list[str] = self._preflight_issues()
        if self._fs.exists(unit_path):
            issues.extend(self._existing_unit_issues(unit_path))
        else:
            issues.extend(self._unit_dir_issues(unit_dir))

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot ensure systemd unit {params.unit_name}",
                issues=issues,
            )

        if self._unit_matches_on_disk(unit_path) and self._runtime_state_matches():
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"systemd unit {params.unit_name} already at desired state"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to ensure systemd unit {params.unit_name}",
        )

    def _runtime_state_matches(self) -> bool:
        params = self._params
        enabled_state = _query_systemctl(
            self._pr, params.scope, "is-enabled", params.unit_name
        )
        if not _enable_state_matches(enabled_state, params.enabled):
            return False
        active_state = _query_systemctl(
            self._pr, params.scope, "is-active", params.unit_name
        )
        return _active_state_matches(active_state, params.started)

    def _read_existing_unit(self) -> str | None:
        path = self._paths.unit_path
        if not self._fs.is_file(path):
            return None
        try:
            return self._fs.read_text_file(path)
        except FsError:
            return None

    def _write_unit(self) -> Result | None:
        path = self._paths.unit_path
        try:
            self._fs.write_text_file(path, self._params.unit_content)
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {path}: {e}")
        return None

    def _run_systemctl(self, code: str, *argv: str) -> Result | None:
        """Run a mutating systemctl invocation. Returns a failure Result on
        any error (raised typed error, or non-zero exit), or None on success.
        """
        try:
            result = self._pr.run(_systemctl_argv(self._params.scope, *argv))
        except _PROCESS_ERRORS as e:
            return Result.failure(code, str(e))
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code=code,
                message=f"systemctl {' '.join(argv)} exited {result.exit_code}",
                details=_details_from(result),
            )
        return None

    def _apply_enabled(self) -> Result | None:
        verb = "enable" if self._params.enabled else "disable"
        return self._run_systemctl(
            "SYSTEMCTL_ENABLE_FAILED", verb, self._params.unit_name
        )

    def _apply_started(self, content_changed: bool) -> Result | None:
        params = self._params
        if not params.started:
            return self._run_systemctl(
                "SYSTEMCTL_START_FAILED", "stop", params.unit_name
            )
        if content_changed and params.reload_on_change:
            return self._run_systemctl(
                "SYSTEMCTL_START_FAILED", "reload-or-restart", params.unit_name
            )
        return self._run_systemctl(
            "SYSTEMCTL_START_FAILED", "start", params.unit_name
        )

    @override
    def transition(self) -> Result:
        params = self._params
        existing = self._read_existing_unit()
        content_changed = existing is not None and existing != params.unit_content

        write_failure = self._write_unit()
        if write_failure is not None:
            return write_failure

        reload_failure = self._run_systemctl("DAEMON_RELOAD_FAILED", "daemon-reload")
        if reload_failure is not None:
            return reload_failure

        enable_failure = self._apply_enabled()
        if enable_failure is not None:
            return enable_failure

        start_failure = self._apply_started(content_changed)
        if start_failure is not None:
            return start_failure

        return Result.success(
            f"ensured systemd unit {params.unit_name} "
            f"(enabled={params.enabled}, started={params.started})"
        )

    @override
    def rollback(self) -> StateChanger:
        return EnsureSystemdUnitRollbackStateChanger(
            self._params,
            file_system=self._fs,
            process_runner=self._pr,
            env=self._env,
        )


class EnsureSystemdUnitRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureSystemdUnitParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()
        self._paths: _UnitPaths = _UnitPaths.build(params, self._env)

    @property
    def params(self) -> EnsureSystemdUnitParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-systemd-unit-rollback:{self._params.unit_name}"

    def _is_loaded(self) -> bool:
        state = _query_systemctl(
            self._pr, self._params.scope, "is-active", self._params.unit_name
        )
        if state is None:
            return False
        return state != "inactive"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        unit_path = self._paths.unit_path
        issues: list[str] = []

        if self._pr.which("systemctl") is None:
            issues.append("systemctl not on PATH")

        unit_exists = self._fs.exists(unit_path)
        if unit_exists:
            if not self._fs.is_file(unit_path):
                issues.append(
                    f"unit path exists but is not a regular file: {unit_path}"
                )
            else:
                try:
                    existing = self._fs.read_text_file(unit_path)
                except FsError as e:
                    issues.append(f"cannot read unit at {unit_path}: {e}")
                    existing = None
                if existing is not None and existing != params.unit_content:
                    issues.append(
                        f"unit at {unit_path} differs from what we wrote; "
                        f"refusing to remove a unit we don't own"
                    )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back systemd unit {params.unit_name}",
                issues=issues,
            )

        if not unit_exists and not self._is_loaded():
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"systemd unit {params.unit_name} already absent and stopped"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to roll back systemd unit {params.unit_name}",
        )

    def _run_systemctl(self, code: str, *argv: str) -> Result | None:
        try:
            result = self._pr.run(_systemctl_argv(self._params.scope, *argv))
        except _PROCESS_ERRORS as e:
            return Result.failure(code, str(e))
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code=code,
                message=f"systemctl {' '.join(argv)} exited {result.exit_code}",
                details=_details_from(result),
            )
        return None

    @override
    def transition(self) -> Result:
        params = self._params
        unit_path = self._paths.unit_path

        # Best-effort stop and disable: tolerate non-zero exit (unit may be
        # already inactive / not enabled), but surface launch errors.
        try:
            self._pr.run(_systemctl_argv(params.scope, "stop", params.unit_name))
        except _PROCESS_ERRORS as e:
            return Result.failure("SYSTEMCTL_STOP_FAILED", str(e))
        try:
            self._pr.run(_systemctl_argv(params.scope, "disable", params.unit_name))
        except _PROCESS_ERRORS as e:
            return Result.failure("SYSTEMCTL_DISABLE_FAILED", str(e))

        try:
            self._fs.delete_file(unit_path)
        except FsNotFound:
            return Result.skipped(f"{unit_path} already gone")
        except FsError as e:
            return Result.failure(
                "UNLINK_FAILED",
                f"failed to remove {unit_path}: {e}",
            )

        reload_failure = self._run_systemctl("DAEMON_RELOAD_FAILED", "daemon-reload")
        if reload_failure is not None:
            return reload_failure

        return Result.success(f"removed systemd unit {params.unit_name}")
