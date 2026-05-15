from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.http import (
    HttpError,
    HttpNetworkError,
    HttpNotFound,
    HttpServerError,
)
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.failing_http_client import FailingHttpClient
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


PREFIX = Path("/opt/homebrew")
URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"


def _rig() -> tuple[
    InMemoryFileSystem,
    FailingProcessRunner,
    FailingHttpClient,
    ScriptedEnv,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))

    inner_pr = ScriptedProcessRunner()
    inner_pr.register_executable("bash")
    pr = FailingProcessRunner(inner_pr)

    inner_http = ScriptedHttpClient()
    from statectl._interfaces.http import HttpResponse

    inner_http.register_response(URL, HttpResponse(status_code=200, body="#!/bin/bash", headers={}))
    http = FailingHttpClient(inner_http)

    return fs, pr, http, ScriptedEnv.darwin()


def _changer(
    fs: InMemoryFileSystem,
    pr: FailingProcessRunner,
    http: FailingHttpClient,
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


HTTP_MATRIX: list[tuple[HttpError, str]] = [
    (HttpNotFound("404 not found", url=URL), "HTTP_NOT_FOUND"),
    (HttpServerError("500 server", url=URL), "HTTP_SERVER_ERROR"),
    (HttpNetworkError("dns", url=URL), "HTTP_NETWORK_ERROR"),
]


@pytest.mark.parametrize(
    "error, code",
    HTTP_MATRIX,
    ids=[type(e).__name__ for e, _ in HTTP_MATRIX],
)
def test_each_http_error_maps_to_specific_failure_code(
    error: HttpError, code: str
) -> None:
    fs, pr, http, env = _rig()
    http.fail("get", error)
    changer = _changer(fs, pr, http, env)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == code


PROCESS_MATRIX: list[tuple[ProcessError, str]] = [
    (ProcessNotFound("bash missing"), "PROCESS_NOT_FOUND"),
    (ProcessTimeout("too long"), "PROCESS_TIMEOUT"),
    (ProcessDecodeError("bad bytes"), "PROCESS_DECODE_ERROR"),
    (ProcessLaunchError("os boom"), "PROCESS_LAUNCH_ERROR"),
]


@pytest.mark.parametrize(
    "error, code",
    PROCESS_MATRIX,
    ids=[type(e).__name__ for e, _ in PROCESS_MATRIX],
)
def test_each_process_error_maps_to_specific_failure_code(
    error: ProcessError, code: str
) -> None:
    fs, pr, http, env = _rig()
    pr.fail("run", error)
    changer = _changer(fs, pr, http, env)

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == code


def test_non_zero_exit_maps_to_install_failed() -> None:
    from statectl._interfaces.process import ProcessResult

    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    inner_pr = ScriptedProcessRunner()
    inner_pr.register_executable("bash")
    inner_pr.register(
        ("bash",),
        ProcessResult(exit_code=1, stdout="", stderr="boom", duration_ms=10),
    )
    inner_http = ScriptedHttpClient()
    from statectl._interfaces.http import HttpResponse

    inner_http.register_response(URL, HttpResponse(status_code=200, body="x", headers={}))

    changer = EnsureHomebrewInstalledStateChanger(
        EnsureHomebrewInstalledParameters(
            brew_prefix=PREFIX,
            install_script_url=URL,
            accept_eula=True,
        ),
        file_system=fs,
        process_runner=inner_pr,
        http_client=inner_http,
        env=ScriptedEnv.darwin(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "INSTALL_FAILED"
    assert result.details["exit_code"] == "1"


def test_unexpected_runtime_error_propagates() -> None:
    fs, pr, http, env = _rig()
    http.fail("get", RuntimeError("unexpected"))
    changer = _changer(fs, pr, http, env)

    with pytest.raises(RuntimeError, match="unexpected"):
        changer.transition()
