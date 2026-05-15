from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, override

from statectl._interfaces.env import Env
from statectl._interfaces.fs import FileSystem, FsError
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


_OUTPUT_CAP: int = 4096
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")

Scope = Literal["user", "system"]


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class EnsureLaunchdAgentParameters(Parameters):
    label: str
    plist_content: str
    scope: Scope
    loaded: bool = True
    domain_target: str | None = None


@dataclass(frozen=True)
class _ProbeError:
    message: str


def _details_from(result: ProcessResult) -> dict[str, str]:
    return {
        "exit_code": str(result.exit_code),
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "duration_ms": str(result.duration_ms),
    }


def _probe(pr: ProcessRunner, argv: tuple[str, ...]) -> ProcessResult | _ProbeError:
    try:
        return pr.run(argv)
    except ProcessNotFound as e:
        return _ProbeError(f"launchctl probe failed (not found): {e}")
    except ProcessTimeout as e:
        return _ProbeError(f"launchctl probe timed out: {e}")
    except ProcessDecodeError as e:
        return _ProbeError(f"launchctl probe decode error: {e}")
    except ProcessLaunchError as e:
        return _ProbeError(f"launchctl probe launch error: {e}")


def _extract_plist_label(plist_content: str) -> str | None:
    """Returns the value of the <Label> key in a plist, or None if not parsable
    or no Label key present."""
    try:
        root = ET.fromstring(plist_content)
    except ET.ParseError:
        return None
    # plist structure: <plist><dict><key>Label</key><string>...</string>...</dict></plist>
    dict_elem = root.find("dict")
    if dict_elem is None and root.tag == "dict":
        dict_elem = root
    if dict_elem is None:
        return None
    children = list(dict_elem)
    for i, child in enumerate(children):
        if child.tag == "key" and (child.text or "").strip() == "Label":
            if i + 1 < len(children) and children[i + 1].tag == "string":
                return (children[i + 1].text or "").strip()
    return None


def _plist_path_for(scope: Scope, label: str, env: Env) -> Path:
    if scope == "user":
        return env.user_home() / "Library" / "LaunchAgents" / f"{label}.plist"
    return Path("/Library/LaunchDaemons") / f"{label}.plist"


def _loaded_probe_argv(
    label: str, domain_target: str | None
) -> tuple[str, ...]:
    if domain_target is not None:
        return ("launchctl", "print", f"{domain_target}/{label}")
    return ("launchctl", "list", label)


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

    def _plist_path(self) -> Path:
        return _plist_path_for(self._params.scope, self._params.label, self._env)

    @override
    def name(self) -> str:
        return f"ensure-launchd-agent:{self._params.scope}/{self._params.label}"

    def _preflight_issues(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if self._env.platform() != "darwin":
            issues.append(
                f"launchd is darwin-only; current platform: {self._env.platform()}"
            )
        if not _LABEL_RE.match(params.label):
            issues.append(f"invalid label: {params.label!r}")
        if self._pr.which("launchctl") is None:
            issues.append("launchctl binary not on PATH")
        plist_label = _extract_plist_label(params.plist_content)
        if plist_label is None:
            issues.append("plist_content is not valid XML or has no Label key")
        elif plist_label != params.label:
            issues.append(
                f"plist Label mismatch: plist has {plist_label!r}, params has {params.label!r}"
            )
        return issues

    def _is_loaded(self) -> bool | _ProbeError:
        argv = _loaded_probe_argv(self._params.label, self._params.domain_target)
        probe = _probe(self._pr, argv)
        if isinstance(probe, _ProbeError):
            return probe
        return probe.exit_code == 0

    def _assess_existing_plist(self, plist_path: Path) -> StateAssessment | None:
        """Return an INVALID/READY assessment if existing plist diverges in a
        way that demands special handling; None if it matches our content
        (caller continues to the loaded-check)."""
        params = self._params
        if not self._fs.is_file(plist_path):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"path exists but is not a regular file: {plist_path}",
                issues=[f"path exists but is not a regular file: {plist_path}"],
            )
        try:
            existing = self._fs.read_text_file(plist_path)
        except FsError as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot read existing plist at {plist_path}",
                issues=[f"cannot read existing plist to compare: {e}"],
            )
        if existing == params.plist_content:
            return None
        existing_label = _extract_plist_label(existing)
        if existing_label is not None and existing_label != params.label:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"refusing to overwrite plist owned by {existing_label!r}",
                issues=[
                    f"plist at {plist_path} has different content and Label "
                    f"{existing_label!r}; refusing to overwrite"
                ],
            )
        # Same label, different content — we own it, will overwrite.
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to update plist {plist_path}",
        )

    def _assess_missing_plist(self, plist_path: Path) -> StateAssessment:
        parent = plist_path.parent
        parent_issues: list[str] = []
        if not self._fs.exists(parent):
            parent_issues.append(f"plist directory does not exist: {parent}")
        elif not self._fs.is_dir(parent):
            parent_issues.append(f"plist directory is not a directory: {parent}")
        elif not self._fs.is_writable(parent):
            parent_issues.append(f"plist directory is not writable: {parent}")
        if parent_issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot write plist at {plist_path}",
                issues=parent_issues,
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to write plist {plist_path}",
        )

    def _assess_loaded(self, plist_path: Path) -> StateAssessment:
        params = self._params
        if not params.loaded:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"plist {plist_path} in place; loaded not required",
            )
        loaded = self._is_loaded()
        if isinstance(loaded, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot determine load state of {params.label}",
                issues=[loaded.message],
            )
        if loaded:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"plist {plist_path} in place and loaded",
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"plist {plist_path} in place; ready to load",
        )

    @override
    def assess_state(self) -> StateAssessment:
        issues = self._preflight_issues()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot ensure launchd agent {self._params.label}",
                issues=issues,
            )

        plist_path = self._plist_path()
        if not self._fs.exists(plist_path):
            return self._assess_missing_plist(plist_path)

        existing_assessment = self._assess_existing_plist(plist_path)
        if existing_assessment is not None:
            return existing_assessment
        return self._assess_loaded(plist_path)

    def _write_plist(self, plist_path: Path) -> Result | None:
        try:
            self._fs.write_text_file(plist_path, self._params.plist_content)
        except FsError as e:
            return Result.failure(
                "WRITE_FAILED", f"failed to write plist {plist_path}: {e}"
            )
        return None

    def _load_argv(self, plist_path: Path) -> tuple[str, ...]:
        if self._params.domain_target is not None:
            return ("launchctl", "bootstrap", self._params.domain_target, str(plist_path))
        return ("launchctl", "load", "-w", str(plist_path))

    def _run_launchctl(
        self, argv: tuple[str, ...], failure_code: str
    ) -> Result:
        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return Result.failure("LAUNCHCTL_NOT_FOUND", str(e))
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
                code=failure_code,
                message=f"{' '.join(argv)} exited {result.exit_code}",
                details=details,
            )
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"{' '.join(argv)} exited 0",
            details=details,
        )

    @override
    def transition(self) -> Result:
        params = self._params
        plist_path = self._plist_path()

        if not self._fs.exists(plist_path) or self._needs_rewrite(plist_path):
            write_failure = self._write_plist(plist_path)
            if write_failure is not None:
                return write_failure

        if not params.loaded:
            return Result.success(f"wrote plist {plist_path}")

        # Verify the plist didn't vanish before we try to load it.
        if not self._fs.exists(plist_path):
            return Result.failure(
                "PLIST_VANISHED",
                f"plist disappeared before load: {plist_path}",
            )

        load_result = self._run_launchctl(
            self._load_argv(plist_path), failure_code="LAUNCHCTL_LOAD_FAILED"
        )
        if load_result.status is not ResultStatus.SUCCESS:
            return load_result
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"loaded launchd agent {params.label}",
            details=load_result.details,
        )

    def _needs_rewrite(self, plist_path: Path) -> bool:
        try:
            existing = self._fs.read_text_file(plist_path)
        except FsError:
            return True
        return existing != self._params.plist_content

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

    def _plist_path(self) -> Path:
        return _plist_path_for(self._params.scope, self._params.label, self._env)

    @override
    def name(self) -> str:
        return (
            f"ensure-launchd-agent-rollback:{self._params.scope}/{self._params.label}"
        )

    def _preflight_issues(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if self._env.platform() != "darwin":
            issues.append(
                f"launchd is darwin-only; current platform: {self._env.platform()}"
            )
        if not _LABEL_RE.match(params.label):
            issues.append(f"invalid label: {params.label!r}")
        if self._pr.which("launchctl") is None:
            issues.append("launchctl binary not on PATH")
        return issues

    def _is_loaded(self) -> bool | _ProbeError:
        argv = _loaded_probe_argv(self._params.label, self._params.domain_target)
        probe = _probe(self._pr, argv)
        if isinstance(probe, _ProbeError):
            return probe
        return probe.exit_code == 0

    def _verify_existing_plist(self, plist_path: Path) -> StateAssessment | None:
        if not self._fs.is_file(plist_path):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"refusing to remove non-file path: {plist_path}",
                issues=[f"refusing to remove non-file path: {plist_path}"],
            )
        try:
            existing = self._fs.read_text_file(plist_path)
        except FsError as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot read plist at {plist_path}",
                issues=[f"cannot read plist to verify ownership: {e}"],
            )
        if existing != self._params.plist_content:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"plist content drift at {plist_path}",
                issues=[
                    f"plist at {plist_path} differs from what we wrote; "
                    f"refusing to roll back"
                ],
            )
        return None

    @override
    def assess_state(self) -> StateAssessment:
        issues = self._preflight_issues()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back launchd agent {self._params.label}",
                issues=issues,
            )

        plist_path = self._plist_path()
        plist_exists = self._fs.exists(plist_path)
        loaded = self._is_loaded()
        if isinstance(loaded, _ProbeError):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot determine load state of {self._params.label}",
                issues=[loaded.message],
            )

        if not plist_exists and not loaded:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"plist {plist_path} absent and not loaded",
            )

        if plist_exists:
            verify_failure = self._verify_existing_plist(plist_path)
            if verify_failure is not None:
                return verify_failure

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to roll back launchd agent {self._params.label}",
        )

    def _unload_argv(self, plist_path: Path) -> tuple[str, ...]:
        if self._params.domain_target is not None:
            return (
                "launchctl",
                "bootout",
                f"{self._params.domain_target}/{self._params.label}",
            )
        return ("launchctl", "unload", "-w", str(plist_path))

    def _run_unload(self, plist_path: Path) -> Result | None:
        try:
            result = self._pr.run(self._unload_argv(plist_path))
        except ProcessNotFound as e:
            return Result.failure("LAUNCHCTL_NOT_FOUND", str(e))
        except ProcessTimeout as e:
            return Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return Result.failure("PROCESS_LAUNCH_ERROR", str(e))
        if result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="LAUNCHCTL_UNLOAD_FAILED",
                message=f"unload exited {result.exit_code}",
                details=_details_from(result),
            )
        return None

    @override
    def transition(self) -> Result:
        plist_path = self._plist_path()

        # Best-effort unload; only fail if launchctl is truly broken / errored.
        loaded = self._is_loaded()
        if isinstance(loaded, _ProbeError):
            return Result.failure("LAUNCHCTL_PROBE_FAILED", loaded.message)
        if loaded:
            unload_failure = self._run_unload(plist_path)
            if unload_failure is not None:
                return unload_failure

        if self._fs.exists(plist_path):
            try:
                self._fs.delete_file(plist_path)
            except FsError as e:
                return Result.failure(
                    "UNLINK_FAILED", f"failed to remove plist {plist_path}: {e}"
                )

        return Result.success(f"rolled back launchd agent {self._params.label}")
