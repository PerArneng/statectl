from __future__ import annotations

from pathlib import Path

from statectl._interfaces.http import HttpResponse
from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


PREFIX = Path("/opt/homebrew")
URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"


def _rig(brew_after_install: bool = True) -> tuple[
    InMemoryFileSystem,
    ScriptedProcessRunner,
    ScriptedHttpClient,
    ScriptedEnv,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))

    pr = ScriptedProcessRunner()
    pr.register_executable("bash")

    def _run_install(_argv: tuple[str, ...]) -> ProcessResult:
        if brew_after_install:
            fs.add_dir(PREFIX)
            fs.add_dir(PREFIX / "bin")
            fs.add_file(
                PREFIX / "bin" / "brew",
                content="#!/bin/bash",
                mode=0o755,
            )
        return ProcessResult(exit_code=0, stdout="installed", stderr="", duration_ms=42)

    # Register a generic 0 result; we'll patch the FS in a wrapper.
    pr.register(("bash",), ProcessResult(exit_code=0, stdout="installed", stderr="", duration_ms=42))

    http = ScriptedHttpClient()
    http.register_response(
        URL, HttpResponse(status_code=200, body="#!/bin/bash\necho install", headers={})
    )
    env = ScriptedEnv.darwin()
    # store the side-effect on the fs so the test can simulate the install
    # creating the brew binary after `run`
    _run_install  # unused helper kept for clarity
    return fs, pr, http, env


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    http: ScriptedHttpClient,
    env: ScriptedEnv,
) -> EnsureHomebrewInstalledStateChanger:
    return EnsureHomebrewInstalledStateChanger(
        EnsureHomebrewInstalledParameters(
            brew_prefix=PREFIX,
            install_script_url=URL,
            accept_eula=True,
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=env,
    )


def test_success_when_install_produces_brew_binary() -> None:
    fs, pr, http, env = _rig()
    # Simulate the install script creating the brew binary
    fs.add_dir(PREFIX)
    fs.add_dir(PREFIX / "bin")
    fs.add_file(PREFIX / "bin" / "brew", content="#!/bin/bash", mode=0o755)
    changer = _changer(fs, pr, http, env)

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["exit_code"] == "0"
    assert "duration_ms" in result.details


def test_success_records_http_get_and_bash_run() -> None:
    fs, pr, http, env = _rig()
    fs.add_dir(PREFIX)
    fs.add_dir(PREFIX / "bin")
    fs.add_file(PREFIX / "bin" / "brew", content="#!/bin/bash", mode=0o755)
    changer = _changer(fs, pr, http, env)

    changer.transition()

    assert len(http.calls) == 1
    assert http.calls[0].method == "get"
    assert http.calls[0].url == URL

    assert len(pr.calls) == 1
    assert pr.calls[0].argv[0] == "bash"
    assert pr.calls[0].env == {"NONINTERACTIVE": "1"}


def test_failure_when_install_script_returns_zero_but_brew_binary_missing() -> None:
    fs, pr, http, env = _rig()
    # Do NOT add the brew binary; the install script returned 0 but the
    # sentinel didn't materialise.
    changer = _changer(fs, pr, http, env)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "BREW_MISSING_AFTER_INSTALL"


def test_long_stdout_is_truncated_in_details() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    fs.add_dir(PREFIX)
    fs.add_dir(PREFIX / "bin")
    fs.add_file(PREFIX / "bin" / "brew", content="#!/bin/bash", mode=0o755)
    huge = "x" * 100_000
    pr = ScriptedProcessRunner()
    pr.register_executable("bash")
    pr.register(("bash",), ProcessResult(exit_code=0, stdout=huge, stderr="", duration_ms=0))
    http = ScriptedHttpClient()
    http.register_response(
        URL, HttpResponse(status_code=200, body="#!/bin/bash", headers={})
    )
    env = ScriptedEnv.darwin()

    changer = _changer(fs, pr, http, env)

    result = changer.transition()

    assert len(result.details["stdout"]) < len(huge)
    assert "truncated" in result.details["stdout"]
