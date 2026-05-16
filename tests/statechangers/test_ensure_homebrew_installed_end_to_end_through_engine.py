from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.http import HttpResponse
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


PREFIX = Path("/opt/homebrew")
URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"


def _engine(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    http: ScriptedHttpClient,
    env: ScriptedEnv,
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=env,
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


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


def test_engine_skips_when_brew_already_installed() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    fs.add_dir(PREFIX)
    fs.add_dir(PREFIX / "bin")
    fs.add_file(PREFIX / "bin" / "brew", content="#!/bin/bash", mode=0o755)

    pr = ScriptedProcessRunner()
    pr.register_executable("bash")
    http = ScriptedHttpClient()
    env = ScriptedEnv.darwin()

    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED
    assert http.calls == []
    assert pr.calls == []


def test_engine_halts_on_invalid_when_not_darwin() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    pr = ScriptedProcessRunner()
    http = ScriptedHttpClient()
    env = ScriptedEnv.linux()

    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
    assert http.calls == []
    assert pr.calls == []


def test_engine_runs_install_and_post_assess_succeeds() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    fs.add_dir(PREFIX)
    fs.add_dir(PREFIX / "bin")

    pr = ScriptedProcessRunner()
    pr.register_executable("bash")
    pr.register(
        ("bash",), ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=10)
    )
    # ScriptedHttpClient.get serves the install script body; we then need the
    # post-assess to find the brew binary. We simulate the install side effect
    # by registering a custom http client subclass that materialises the binary
    # on download. Simpler approach: pre-create the binary so the script "run"
    # is essentially a no-op, and the post-assess passes.
    fs.add_file(PREFIX / "bin" / "brew", content="#!/bin/bash", mode=0o755)
    # But the engine assesses first; if brew is already there, the engine
    # returns SKIPPED_ALREADY_APPLIED. To exercise the install path we delete
    # the binary and rely on a wrapper http client that creates it.

    fs.delete_file(PREFIX / "bin" / "brew")

    class _MaterialisingHttp(ScriptedHttpClient):
        def get(self, url, headers=None, timeout=None):  # type: ignore[override]
            fs.add_file(
                PREFIX / "bin" / "brew", content="#!/bin/bash", mode=0o755
            )
            return HttpResponse(status_code=200, body="#!/bin/bash", headers={})

    http = _MaterialisingHttp()
    env = ScriptedEnv.darwin()

    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
    assert len(pr.calls) == 1


def test_engine_marks_failed_when_post_assess_sentinel_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))

    pr = ScriptedProcessRunner()
    pr.register_executable("bash")
    pr.register(
        ("bash",), ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
    )
    http = ScriptedHttpClient()
    http.register_response(URL, HttpResponse(status_code=200, body="#!/bin/bash", headers={}))
    env = ScriptedEnv.darwin()

    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    report_result = result.reports[0].result
    assert report_result is not None
    assert report_result.code == "BREW_MISSING_AFTER_INSTALL"
