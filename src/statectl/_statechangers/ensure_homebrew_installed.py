from __future__ import annotations

import stat
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
    StateAssessment,
    StateChanger,
)


_DEFAULT_INSTALL_SCRIPT_URL: str = (
    "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
)
_OUTPUT_CAP: int = 4096


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


@dataclass(frozen=True)
class EnsureHomebrewInstalledParameters(Parameters):
    brew_prefix: Path
    install_script_url: str = _DEFAULT_INSTALL_SCRIPT_URL
    accept_eula: bool = False


class EnsureHomebrewInstalledStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureHomebrewInstalledParameters,
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
    def params(self) -> EnsureHomebrewInstalledParameters:
        return self._params

    def _brew_binary(self) -> Path:
        return self._params.brew_prefix / "bin" / "brew"

    def _brew_present(self) -> bool:
        binary = self._brew_binary()
        if not self._fs.is_file(binary):
            return False
        mode = self._fs.stat_mode(binary)
        if mode is None:
            return False
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    @override
    def name(self) -> str:
        return f"ensure-homebrew-installed:{self._params.brew_prefix}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues: list[str] = []

        if self._env.platform() != "darwin":
            issues.append("Homebrew bootstrap is macOS-only")

        parsed = urlparse(params.install_script_url)
        if parsed.scheme != "https":
            issues.append(
                f"install script must be https: {params.install_script_url}"
            )

        prefix_parent = params.brew_prefix.parent
        if not self._fs.is_writable(prefix_parent):
            issues.append(f"prefix parent not writable: {prefix_parent}")

        brew_present = self._brew_present()
        if not brew_present and not params.accept_eula:
            issues.append(
                "non-interactive install requires accept_eula=True"
            )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot install Homebrew at {params.brew_prefix}",
                issues=issues,
            )

        if brew_present:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"brew already present at {self._brew_binary()}",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to install Homebrew at {params.brew_prefix}",
        )

    def _fetch_script(self, script_path: Path) -> Result | None:
        try:
            response = self._http.get(self._params.install_script_url)
        except HttpNotFound as e:
            return Result.failure("HTTP_NOT_FOUND", str(e))
        except HttpServerError as e:
            return Result.failure("HTTP_SERVER_ERROR", str(e))
        except HttpNetworkError as e:
            return Result.failure("HTTP_NETWORK_ERROR", str(e))

        try:
            self._fs.write_text_file(script_path, response.body)
        except FsError as e:
            return Result.failure(
                "SCRIPT_WRITE_FAILED",
                f"failed to write install script to {script_path}: {e}",
            )
        return None

    def _run_install_script(
        self, script_path: Path
    ) -> tuple[Result | None, dict[str, str]]:
        try:
            run_result = self._pr.run(
                ("bash", str(script_path)),
                env={"NONINTERACTIVE": "1"},
            )
        except ProcessNotFound as e:
            return Result.failure("PROCESS_NOT_FOUND", str(e)), {}
        except ProcessTimeout as e:
            return Result.failure("PROCESS_TIMEOUT", str(e)), {}
        except ProcessDecodeError as e:
            return Result.failure("PROCESS_DECODE_ERROR", str(e)), {}
        except ProcessLaunchError as e:
            return Result.failure("PROCESS_LAUNCH_ERROR", str(e)), {}

        details: dict[str, str] = {
            "exit_code": str(run_result.exit_code),
            "stdout": _truncate(run_result.stdout),
            "stderr": _truncate(run_result.stderr),
            "duration_ms": str(run_result.duration_ms),
        }
        if run_result.exit_code != 0:
            return Result(
                status=ResultStatus.FAILURE,
                code="INSTALL_FAILED",
                message=f"install script exited {run_result.exit_code}",
                details=details,
            ), details
        return None, details

    @override
    def transition(self) -> Result:
        params = self._params
        try:
            dest_dir = self._fs.create_temp_folder(prefix="statectl-brew-")
        except FsError as e:
            return Result.failure("TEMP_DIR_FAILED", f"failed to create temp dir: {e}")

        script_path = dest_dir / "install.sh"
        fetch_failure = self._fetch_script(script_path)
        if fetch_failure is not None:
            return fetch_failure

        run_failure, details = self._run_install_script(script_path)
        if run_failure is not None:
            return run_failure

        if not self._brew_present():
            return Result(
                status=ResultStatus.FAILURE,
                code="BREW_MISSING_AFTER_INSTALL",
                message=(
                    f"install script returned 0 but {self._brew_binary()} "
                    f"is missing or not executable"
                ),
                details=details,
            )

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"installed Homebrew at {params.brew_prefix}",
            details=details,
        )
