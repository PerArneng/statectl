from __future__ import annotations

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import BrewCaskParameters, BrewCaskStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(pr: ScriptedProcessRunner) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.darwin(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _changer(pr: ScriptedProcessRunner, **kw: object) -> BrewCaskStateChanger:
    return BrewCaskStateChanger(
        BrewCaskParameters(name="google-chrome", **kw),  # type: ignore[arg-type]
        process_runner=pr,
    )


def test_engine_skips_when_cask_already_installed() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list"),
        ProcessResult(
            exit_code=0,
            stdout="google-chrome 121.0.6167.85\n",
            stderr="",
            duration_ms=0,
        ),
    )

    engine = _engine(pr)
    engine.add(_changer(pr))
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED
    # no install call
    assert not any(c.argv[:2] == ("brew", "install") for c in pr.calls)


def test_engine_halts_on_invalid_when_brew_missing() -> None:
    pr = ScriptedProcessRunner()
    # brew not registered
    engine = _engine(pr)
    engine.add(_changer(pr))
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_runs_install_when_not_installed() -> None:
    """Use a stateful runner so the post-transition assess observes the cask
    as installed."""
    from pathlib import Path
    from typing import Mapping, Sequence, override

    from statectl._interfaces.process import ProcessNotFound, ProcessRunner

    class _StatefulBrewRunner(ProcessRunner):
        def __init__(self) -> None:
            self.installed: bool = False
            self.calls: list[tuple[str, ...]] = []

        @override
        def which(self, name: str) -> Path | None:
            return Path("/usr/bin/brew") if name == "brew" else None

        @override
        def run(
            self,
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
            stdin: str | None = None,
            timeout: float | None = None,
        ) -> ProcessResult:
            argv_t = tuple(argv)
            self.calls.append(argv_t)
            if not argv_t or argv_t[0] != "brew":
                raise ProcessNotFound("brew missing", argv=argv_t)
            if argv_t[:2] == ("brew", "list"):
                if self.installed:
                    return ProcessResult(
                        exit_code=0,
                        stdout="google-chrome 1.0.0\n",
                        stderr="",
                        duration_ms=0,
                    )
                return ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0)
            if argv_t[:2] == ("brew", "info"):
                return ProcessResult(exit_code=0, stdout="info", stderr="", duration_ms=0)
            if argv_t[:2] == ("brew", "install"):
                self.installed = True
                return ProcessResult(
                    exit_code=0, stdout="installed", stderr="", duration_ms=10
                )
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)

    pr = _StatefulBrewRunner()
    engine = StateCtl(
        logger=DefaultLogger("test"),
        file_system=InMemoryFileSystem(),
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.darwin(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )
    engine.add(
        BrewCaskStateChanger(
            BrewCaskParameters(name="google-chrome"),
            process_runner=pr,
        )
    )
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
    assert any(c[:2] == ("brew", "install") for c in pr.calls)


def test_engine_halts_on_failed_transition_for_non_zero_install() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "info"),
        ProcessResult(exit_code=0, stdout="info", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "install"),
        ProcessResult(exit_code=1, stdout="", stderr="boom", duration_ms=10),
    )

    engine = _engine(pr)
    engine.add(_changer(pr))
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    rr = result.reports[0].result
    assert rr is not None
    assert rr.code == "BREW_CASK_INSTALL_FAILED"
