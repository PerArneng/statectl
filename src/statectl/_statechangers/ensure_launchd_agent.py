from __future__ import annotations

import xml.etree.ElementTree as ET
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


Scope = Literal["user", "system"]


_USER_LAUNCH_AGENTS_REL: str = "Library/LaunchAgents"
_SYSTEM_LAUNCH_DAEMONS: Path = Path("/Library/LaunchDaemons")
_OUTPUT_CAP: int = 4096


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


def _parse_plist_label(plist_content: str) -> tuple[str | None, str | None]:
    """Returns (label, error_message). label is None on parse failure or if
    the plist body does not contain a Label key/string pair."""
    try:
        root = ET.fromstring(plist_content)
    except ET.ParseError as e:
        return None, f"plist_content does not parse as XML: {e}"

    dict_node = root if root.tag == "dict" else root.find(".//dict")
    if dict_node is None:
        return None, "plist_content has no <dict> element"

    children = list(dict_node)
    for idx, child in enumerate(children):
        if child.tag == "key" and (child.text or "").strip() == "Label":
            if idx + 1 >= len(children):
                return None, "plist Label key has no value"
            value_node = children[idx + 1]
            if value_node.tag != "string":
                return None, f"plist Label value is not a string: <{value_node.tag}>"
            return (value_node.text or "").strip(), None
    return None, "plist_content does not contain a Label key"


@dataclass(frozen=True)
class EnsureLaunchdAgentParameters(Parameters):
    label: str
    plist_content: str
    scope: Scope
    loaded: bool = True
    domain_target: str | None = None


class EnsureLaunchdAgentStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureLaunchdAgentParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> EnsureLaunchdAgentParameters:
        return self._params

    def _plist_dir(self) -> Path:
        if self._params.scope == "system":
            return _SYSTEM_LAUNCH_DAEMONS
        return self._env.user_home() / _USER_LAUNCH_AGENTS_REL

    def _plist_path(self) -> Path:
        return self._plist_dir() / f"{self._params.label}.plist"

    def _effective_domain_target(self) -> str | None:
        if self._params.domain_target is not None:
            return self._params.domain_target
        if self._params.scope == "system":
            return "system"
        return None

    def _service_target(self) -> str | None:
        domain = self._effective_domain_target()
        if domain is None:
            return None
        return f"{domain}/{self._params.label}"

    def _is_loaded(self) -> bool:
        service = self._service_target()
        if service is None:
            return False
        try:
            result = self._pr.run(("launchctl", "print", service))
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ):
            return False
        return result.exit_code == 0

    @override
    def name(self) -> str:
        return f"ensure-launchd-agent:{self._params.label}"

    def _preflight_issues(self) -> list[str]:
        params = self._params
        issues: list[str] = []

        if self._env.platform() != "darwin":
            issues.append("launchd is macOS-only (platform is not darwin)")

        if self._pr.which("launchctl") is None:
            issues.append("launchctl not on PATH")

        parsed_label, parse_err = _parse_plist_label(params.plist_content)
        if parse_err is not None:
            issues.append(parse_err)
        elif parsed_label != params.label:
            issues.append(
                f"plist Label mismatch: plist declares {parsed_label!r}, "
                f"params.label is {params.label!r}"
            )

        if params.loaded and self._effective_domain_target() is None:
            issues.append(
                "loaded=True requires explicit domain_target for scope=user "
                "(e.g. 'gui/501')"
            )
        return issues

    def _existing_plist_issues(self, plist_path: Path) -> list[str]:
        params = self._params
        issues: list[str] = []
        if not self._fs.is_file(plist_path):
            issues.append(
                f"plist path exists but is not a regular file: {plist_path}"
            )
            return issues
        try:
            existing = self._fs.read_text_file(plist_path)
        except FsError as e:
            issues.append(f"cannot read existing plist at {plist_path}: {e}")
            return issues
        if existing == params.plist_content:
            return issues
        existing_label, _ = _parse_plist_label(existing)
        if existing_label is not None and existing_label != params.label:
            issues.append(
                f"plist at {plist_path} belongs to a different agent "
                f"(Label={existing_label!r}); refusing to overwrite"
            )
        return issues

    def _plist_dir_issues(self, plist_dir: Path) -> list[str]:
        if not self._fs.exists(plist_dir):
            return [f"plist directory does not exist: {plist_dir}"]
        if not self._fs.is_dir(plist_dir):
            return [f"plist directory is not a directory: {plist_dir}"]
        if not self._fs.is_writable(plist_dir):
            return [f"plist directory is not writable: {plist_dir}"]
        return []

    def _plist_matches_on_disk(self, plist_path: Path) -> bool:
        if not self._fs.is_file(plist_path):
            return False
        try:
            existing = self._fs.read_text_file(plist_path)
        except FsError:
            return False
        return existing == self._params.plist_content

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        plist_dir = self._plist_dir()
        plist_path = self._plist_path()

        issues: list[str] = self._preflight_issues()
        if self._fs.exists(plist_path):
            issues.extend(self._existing_plist_issues(plist_path))
        else:
            issues.extend(self._plist_dir_issues(plist_dir))

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot ensure launchd agent {params.label}",
                issues=issues,
            )

        plist_matches = self._plist_matches_on_disk(plist_path)
        if plist_matches and (not params.loaded or self._is_loaded()):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"launchd agent {params.label} already at desired state"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to ensure launchd agent {params.label}",
        )

    def _write_plist(self) -> Result | None:
        path = self._plist_path()
        try:
            self._fs.write_text_file(path, self._params.plist_content)
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {path}: {e}")
        return None

    def _bootstrap(self) -> Result:
        service = self._service_target()
        plist_path = self._plist_path()
        if service is None:
            return Result.failure(
                "LAUNCHCTL_LOAD_FAILED",
                "no domain_target resolved; cannot bootstrap",
            )
        domain = self._effective_domain_target() or ""
        if not self._fs.is_file(plist_path):
            return Result.failure(
                "PLIST_VANISHED",
                f"plist disappeared before load: {plist_path}",
            )
        try:
            result = self._pr.run(
                ("launchctl", "bootstrap", domain, str(plist_path)),
            )
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ) as e:
            return Result.failure("LAUNCHCTL_LOAD_FAILED", str(e))

        details = _details_from(result)
        if result.exit_code != 0:
            # Legacy fallback for older macOS where `bootstrap` is unavailable
            # or domain is unsupported — try `launchctl load`.
            try:
                legacy = self._pr.run(("launchctl", "load", str(plist_path)))
            except (
                ProcessNotFound,
                ProcessTimeout,
                ProcessDecodeError,
                ProcessLaunchError,
            ) as e:
                return Result(
                    status=ResultStatus.FAILURE,
                    code="LAUNCHCTL_LOAD_FAILED",
                    message=f"bootstrap failed and load raised: {e}",
                    details=details,
                )
            legacy_details = _details_from(legacy)
            if legacy.exit_code != 0:
                return Result(
                    status=ResultStatus.FAILURE,
                    code="LAUNCHCTL_LOAD_FAILED",
                    message=(
                        f"bootstrap exited {result.exit_code}, "
                        f"load exited {legacy.exit_code}"
                    ),
                    details=legacy_details,
                )
            return Result(
                status=ResultStatus.SUCCESS,
                code="OK",
                message=f"loaded {service} via legacy launchctl load",
                details=legacy_details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"bootstrapped {service}",
            details=details,
        )

    @override
    def transition(self) -> Result:
        write_failure = self._write_plist()
        if write_failure is not None:
            return write_failure
        if not self._params.loaded:
            return Result.success(f"wrote plist {self._plist_path()}")
        return self._bootstrap()

    @override
    def rollback(self) -> StateChanger:
        return EnsureLaunchdAgentRollbackStateChanger(
            self._params,
            file_system=self._fs,
            process_runner=self._pr,
            env=self._env,
        )


class EnsureLaunchdAgentRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureLaunchdAgentParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> EnsureLaunchdAgentParameters:
        return self._params

    def _plist_dir(self) -> Path:
        if self._params.scope == "system":
            return _SYSTEM_LAUNCH_DAEMONS
        return self._env.user_home() / _USER_LAUNCH_AGENTS_REL

    def _plist_path(self) -> Path:
        return self._plist_dir() / f"{self._params.label}.plist"

    def _effective_domain_target(self) -> str | None:
        if self._params.domain_target is not None:
            return self._params.domain_target
        if self._params.scope == "system":
            return "system"
        return None

    def _service_target(self) -> str | None:
        domain = self._effective_domain_target()
        if domain is None:
            return None
        return f"{domain}/{self._params.label}"

    def _is_loaded(self) -> bool:
        service = self._service_target()
        if service is None:
            return False
        try:
            result = self._pr.run(("launchctl", "print", service))
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ):
            return False
        return result.exit_code == 0

    @override
    def name(self) -> str:
        return f"ensure-launchd-agent-rollback:{self._params.label}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        plist_path = self._plist_path()
        issues: list[str] = []

        if self._pr.which("launchctl") is None:
            issues.append("launchctl not on PATH")

        plist_exists = self._fs.exists(plist_path)
        if plist_exists:
            if not self._fs.is_file(plist_path):
                issues.append(
                    f"plist path exists but is not a regular file: {plist_path}"
                )
            else:
                try:
                    existing = self._fs.read_text_file(plist_path)
                except FsError as e:
                    issues.append(f"cannot read plist at {plist_path}: {e}")
                    existing = None
                if existing is not None and existing != params.plist_content:
                    issues.append(
                        f"plist at {plist_path} differs from what we wrote; "
                        f"refusing to remove a plist we don't own"
                    )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back launchd agent {params.label}",
                issues=issues,
            )

        if not plist_exists and not self._is_loaded():
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"launchd agent {params.label} already absent and unloaded"
                ),
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to roll back launchd agent {params.label}",
        )

    def _bootout(self) -> Result | None:
        """Unload the service if loaded. Returns a failure Result if bootout
        raises or both bootout/unload exit non-zero; None on success or when
        the service isn't loaded."""
        service = self._service_target()
        plist_path = self._plist_path()
        if service is None:
            # No domain known — fall back to legacy unload by plist path if
            # the file exists; otherwise skip (nothing we can do).
            if not self._fs.is_file(plist_path):
                return None
            try:
                legacy = self._pr.run(("launchctl", "unload", str(plist_path)))
            except (
                ProcessNotFound,
                ProcessTimeout,
                ProcessDecodeError,
                ProcessLaunchError,
            ) as e:
                return Result.failure("LAUNCHCTL_UNLOAD_FAILED", str(e))
            if legacy.exit_code != 0:
                return Result(
                    status=ResultStatus.FAILURE,
                    code="LAUNCHCTL_UNLOAD_FAILED",
                    message=f"launchctl unload exited {legacy.exit_code}",
                    details=_details_from(legacy),
                )
            return None

        try:
            result = self._pr.run(("launchctl", "bootout", service))
        except (
            ProcessNotFound,
            ProcessTimeout,
            ProcessDecodeError,
            ProcessLaunchError,
        ) as e:
            return Result.failure("LAUNCHCTL_UNLOAD_FAILED", str(e))
        if result.exit_code != 0:
            # Legacy fallback to `launchctl unload <plist>`.
            if not self._fs.is_file(plist_path):
                return None
            try:
                legacy = self._pr.run(("launchctl", "unload", str(plist_path)))
            except (
                ProcessNotFound,
                ProcessTimeout,
                ProcessDecodeError,
                ProcessLaunchError,
            ) as e:
                return Result(
                    status=ResultStatus.FAILURE,
                    code="LAUNCHCTL_UNLOAD_FAILED",
                    message=f"bootout failed and unload raised: {e}",
                    details=_details_from(result),
                )
            if legacy.exit_code != 0:
                return Result(
                    status=ResultStatus.FAILURE,
                    code="LAUNCHCTL_UNLOAD_FAILED",
                    message=(
                        f"bootout exited {result.exit_code}, "
                        f"unload exited {legacy.exit_code}"
                    ),
                    details=_details_from(legacy),
                )
        return None

    @override
    def transition(self) -> Result:
        plist_path = self._plist_path()
        unload_failure = self._bootout()
        if unload_failure is not None:
            return unload_failure
        try:
            self._fs.delete_file(plist_path)
        except FsNotFound:
            return Result.skipped(f"{plist_path} already gone")
        except FsError as e:
            return Result.failure(
                "UNLINK_FAILED",
                f"failed to remove {plist_path}: {e}",
            )
        return Result.success(f"removed launchd agent {self._params.label}")
