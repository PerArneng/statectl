from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import override
from urllib.parse import urlparse

from statectl._interfaces.env import Env
from statectl._interfaces.fs import FileSystem, FsError
from statectl._interfaces.http import (
    HttpClient,
    HttpNetworkError,
    HttpNotFound,
    HttpServerError,
)
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealEnv, RealFileSystem, RealHttpClient, RealProcessRunner
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
_SOURCES_DIR: Path = Path("/etc/apt/sources.list.d")
_DEFAULT_KEYRING_DIR: Path = Path("/etc/apt/keyrings")


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


def _normalise_fingerprint(fp: str) -> str:
    return fp.replace(" ", "").upper()


@dataclass(frozen=True)
class InlineKey:
    armored: str
    fingerprint: str


@dataclass(frozen=True)
class UrlKey:
    url: str
    fingerprint: str
    sha256: str | None = None


KeySource = InlineKey | UrlKey


@dataclass(frozen=True)
class AptRepositoryParameters(Parameters):
    name: str
    uri: str
    suite: str
    components: tuple[str, ...]
    signing_key: KeySource
    architectures: tuple[str, ...] = ()
    keyring_path: Path | None = None


def _resolve_keyring_path(params: AptRepositoryParameters) -> Path:
    if params.keyring_path is not None:
        return params.keyring_path
    return _DEFAULT_KEYRING_DIR / f"{params.name}.gpg"


def _sources_file_path(params: AptRepositoryParameters) -> Path:
    return _SOURCES_DIR / f"{params.name}.list"


def _expected_sources_content(params: AptRepositoryParameters) -> str:
    keyring_path = _resolve_keyring_path(params)
    opts: list[str] = []
    if params.architectures:
        opts.append(f"arch={','.join(params.architectures)}")
    opts.append(f"signed-by={keyring_path}")
    opt_str = f"[{' '.join(opts)}] "
    comp_str = " ".join(params.components)
    return f"deb {opt_str}{params.uri} {params.suite} {comp_str}\n"


def _read_keyring_fingerprint(pr: ProcessRunner, keyring_path: Path) -> str | None:
    try:
        result = pr.run(
            ("gpg", "--show-keys", "--with-colons", str(keyring_path)),
        )
    except (ProcessNotFound, ProcessTimeout, ProcessDecodeError, ProcessLaunchError):
        return None
    if result.exit_code != 0:
        return None
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if parts and parts[0] == "fpr" and len(parts) > 9 and parts[9]:
            return _normalise_fingerprint(parts[9])
    return None


class AptRepositoryStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: AptRepositoryParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        http_client: HttpClient | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._http: HttpClient = http_client or RealHttpClient()
        self._env: Env = env or RealEnv()

    @property
    def params(self) -> AptRepositoryParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"apt-repository:{self._params.name}"

    def _inspect_sources(
        self, sources_file: Path, expected: str, issues: list[str]
    ) -> bool:
        if not self._fs.exists(sources_file):
            return False
        if not self._fs.is_file(sources_file):
            issues.append(f"sources file path is not a regular file: {sources_file}")
            return False
        try:
            existing = self._fs.read_text_file(sources_file)
        except FsError as e:
            issues.append(f"cannot read existing sources file: {e}")
            return False
        if existing == expected:
            return True
        issues.append(f"sources file exists with different content: {sources_file}")
        return False

    def _inspect_keyring(
        self, keyring_path: Path, expected_fp: str, issues: list[str]
    ) -> bool:
        if not self._fs.exists(keyring_path):
            return False
        if not self._fs.is_file(keyring_path):
            issues.append(f"keyring path is not a regular file: {keyring_path}")
            return False
        installed_fp = _read_keyring_fingerprint(self._pr, keyring_path)
        if installed_fp is None:
            issues.append(f"cannot read fingerprint from keyring: {keyring_path}")
            return False
        if installed_fp != expected_fp:
            issues.append(
                f"keyring has wrong fingerprint: {installed_fp} != {expected_fp}"
            )
            return False
        return True

    def _check_preconditions(self, keyring_path: Path, issues: list[str]) -> None:
        if self._env.platform() != "linux":
            issues.append("apt repositories require a Debian-family Linux platform")
        if self._pr.which("gpg") is None:
            issues.append("gpg executable not found on PATH")
        self._check_writable_dir(keyring_path.parent, "keyring parent", issues)
        self._check_writable_dir(_SOURCES_DIR, "sources.list.d", issues)
        key = self._params.signing_key
        if isinstance(key, UrlKey):
            if urlparse(key.url).scheme != "https":
                issues.append(f"key URL must be https: {key.url}")

    def _check_writable_dir(self, path: Path, label: str, issues: list[str]) -> None:
        if not self._fs.exists(path):
            issues.append(f"{label} does not exist: {path}")
            return
        if not self._fs.is_dir(path):
            issues.append(f"{label} is not a directory: {path}")
            return
        if not self._fs.is_writable(path):
            issues.append(f"{label} is not writable: {path}")

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        keyring_path = _resolve_keyring_path(params)
        sources_file = _sources_file_path(params)
        expected_sources = _expected_sources_content(params)
        expected_fp = _normalise_fingerprint(params.signing_key.fingerprint)

        issues: list[str] = []
        sources_match = self._inspect_sources(sources_file, expected_sources, issues)
        keyring_match = self._inspect_keyring(keyring_path, expected_fp, issues)

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot configure apt repository {params.name}",
                issues=issues,
            )

        if sources_match and keyring_match:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"apt repository {params.name} already configured",
            )

        self._check_preconditions(keyring_path, issues)
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot configure apt repository {params.name}",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to configure apt repository {params.name}",
        )

    def _materialise_armored(self) -> Result | str:
        key = self._params.signing_key
        if isinstance(key, InlineKey):
            return key.armored
        try:
            response = self._http.get(key.url)
        except HttpNotFound as e:
            return Result.failure("KEY_FETCH_FAILED", str(e))
        except HttpServerError as e:
            return Result.failure("KEY_FETCH_FAILED", str(e))
        except HttpNetworkError as e:
            return Result.failure("KEY_FETCH_FAILED", str(e))
        if key.sha256 is not None:
            digest = hashlib.sha256(response.body.encode("utf-8")).hexdigest()
            if digest.lower() != key.sha256.lower():
                return Result.failure(
                    "KEY_SHA256_MISMATCH",
                    f"sha256 mismatch: got {digest}, expected {key.sha256}",
                )
        return response.body

    def _run_dearmor(
        self, armored_path: Path, keyring_path: Path
    ) -> Result | dict[str, str]:
        try:
            run_result = self._pr.run(
                ("gpg", "--dearmor", "-o", str(keyring_path), str(armored_path)),
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
            "dearmor_exit_code": str(run_result.exit_code),
            "dearmor_stdout": _truncate(run_result.stdout),
            "dearmor_stderr": _truncate(run_result.stderr),
        }
        if run_result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="KEY_DEARMOR_FAILED",
                message=f"gpg --dearmor exited {run_result.exit_code}",
                details=details,
            )
        return details

    def _write_armored(self, armored: str) -> Result | Path:
        try:
            temp_dir = self._fs.create_temp_folder(prefix="statectl-apt-")
        except FsError as e:
            return Result.failure("TEMP_DIR_FAILED", f"failed to create temp dir: {e}")
        armored_path = temp_dir / "key.asc"
        try:
            self._fs.write_text_file(armored_path, armored)
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write armored key: {e}")
        return armored_path

    @override
    def transition(self) -> Result:
        params = self._params
        keyring_path = _resolve_keyring_path(params)
        sources_file = _sources_file_path(params)
        expected_fp = _normalise_fingerprint(params.signing_key.fingerprint)

        armored_or_failure = self._materialise_armored()
        if isinstance(armored_or_failure, Result):
            return armored_or_failure

        armored_path_or_failure = self._write_armored(armored_or_failure)
        if isinstance(armored_path_or_failure, Result):
            return armored_path_or_failure
        armored_path = armored_path_or_failure

        if self._fs.exists(keyring_path):
            try:
                self._fs.delete_file(keyring_path)
            except FsError as e:
                return Result.failure(
                    "WRITE_FAILED", f"failed to remove existing keyring: {e}"
                )

        dearmor_outcome = self._run_dearmor(armored_path, keyring_path)
        if isinstance(dearmor_outcome, Result):
            return dearmor_outcome
        details = dearmor_outcome

        installed_fp = _read_keyring_fingerprint(self._pr, keyring_path)
        details["installed_fingerprint"] = installed_fp or ""
        details["expected_fingerprint"] = expected_fp
        if installed_fp != expected_fp:
            try:
                self._fs.delete_file(keyring_path)
            except FsError:
                pass
            return Result(
                status=ResultStatus.FAILURE,
                code="KEY_FINGERPRINT_MISMATCH",
                message=(
                    f"installed fingerprint {installed_fp} does not match "
                    f"expected {expected_fp}"
                ),
                details=details,
            )

        try:
            self._fs.write_text_file(sources_file, _expected_sources_content(params))
        except FsError as e:
            return Result(
                status=ResultStatus.FAILURE,
                code="WRITE_FAILED",
                message=f"failed to write sources file: {e}",
                details=details,
            )

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"configured apt repository {params.name}",
            details=details,
        )

    @override
    def rollback(self) -> StateChanger:
        return AptRepositoryRollbackStateChanger(
            self._params,
            file_system=self._fs,
            process_runner=self._pr,
            env=self._env,
        )


class AptRepositoryRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: AptRepositoryParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()

    @override
    def name(self) -> str:
        return f"apt-repository-rollback:{self._params.name}"

    def _inspect_sources_for_rollback(
        self, sources_file: Path, expected: str, issues: list[str]
    ) -> None:
        if not self._fs.is_file(sources_file):
            issues.append(f"sources path is not a regular file: {sources_file}")
            return
        try:
            existing = self._fs.read_text_file(sources_file)
        except FsError as e:
            issues.append(f"cannot read sources file: {e}")
            return
        if existing != expected:
            issues.append(
                f"sources file has drifted, refusing to delete: {sources_file}"
            )

    def _inspect_keyring_for_rollback(
        self, keyring_path: Path, expected_fp: str, issues: list[str]
    ) -> None:
        if not self._fs.is_file(keyring_path):
            issues.append(f"keyring path is not a regular file: {keyring_path}")
            return
        installed_fp = _read_keyring_fingerprint(self._pr, keyring_path)
        if installed_fp is None:
            issues.append(f"cannot read fingerprint from keyring: {keyring_path}")
            return
        if installed_fp != expected_fp:
            issues.append(
                f"keyring has drifted, refusing to delete: {keyring_path}"
            )

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        keyring_path = _resolve_keyring_path(params)
        sources_file = _sources_file_path(params)
        sources_exists = self._fs.exists(sources_file)
        keyring_exists = self._fs.exists(keyring_path)

        if not sources_exists and not keyring_exists:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"apt repository {params.name} already removed",
            )

        issues: list[str] = []
        if sources_exists:
            self._inspect_sources_for_rollback(
                sources_file, _expected_sources_content(params), issues
            )
        if keyring_exists:
            self._inspect_keyring_for_rollback(
                keyring_path,
                _normalise_fingerprint(params.signing_key.fingerprint),
                issues,
            )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back apt repository {params.name}",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove apt repository {params.name}",
        )

    @override
    def transition(self) -> Result:
        params = self._params
        keyring_path = _resolve_keyring_path(params)
        sources_file = _sources_file_path(params)
        for path in (sources_file, keyring_path):
            if not self._fs.exists(path):
                continue
            try:
                self._fs.delete_file(path)
            except FsError as e:
                return Result.failure(
                    "UNLINK_FAILED", f"failed to remove {path}: {e}"
                )
        return Result.success(f"removed apt repository {params.name}")
