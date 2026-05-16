from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


class _StatefulBrewRunner(ScriptedProcessRunner):
    """ScriptedProcessRunner that flips an internal "installed" set on
    `brew install` / `brew uninstall`, so subsequent `brew list --formula`
    calls reflect the new state. Used to exercise the engine's post-assess
    after a successful transition.
    """

    def __init__(self) -> None:
        super().__init__()
        self._installed: set[str] = set()
        self._pinned: set[str] = set()
        self.register_executable("brew")

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
        argv_tuple = tuple(argv)
        if len(argv_tuple) >= 3 and argv_tuple[:2] == ("brew", "install"):
            target = argv_tuple[2].rsplit("/", 1)[-1].split("@", 1)[0]
            self._installed.add(target)
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0, stdout="ok", stderr="", duration_ms=0
            )
        if len(argv_tuple) >= 3 and argv_tuple[:2] == ("brew", "uninstall"):
            self._installed.discard(argv_tuple[2])
            self._pinned.discard(argv_tuple[2])
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0, stdout="ok", stderr="", duration_ms=0
            )
        if len(argv_tuple) >= 3 and argv_tuple[:2] == ("brew", "pin"):
            self._pinned.add(argv_tuple[2])
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0, stdout="", stderr="", duration_ms=0
            )
        if argv_tuple[:3] == ("brew", "list", "--formula"):
            name = argv_tuple[3]
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            installed = name in self._installed
            return ProcessResult(
                exit_code=0 if installed else 1,
                stdout="",
                stderr="",
                duration_ms=0,
            )
        if argv_tuple[:3] == ("brew", "list", "--versions"):
            name = argv_tuple[3]
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            if name in self._installed:
                return ProcessResult(
                    exit_code=0,
                    stdout=f"{name} 14.1.0\n",
                    stderr="",
                    duration_ms=0,
                )
            return ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0)
        if argv_tuple[:3] == ("brew", "list", "--pinned"):
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0,
                stdout="\n".join(sorted(self._pinned)),
                stderr="",
                duration_ms=0,
            )
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


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


def test_engine_installs_and_post_assess_succeeds() -> None:
    pr = _StatefulBrewRunner()
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    engine = _engine(pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_skips_when_already_installed() -> None:
    pr = _StatefulBrewRunner()
    pr._installed.add("ripgrep")  # noqa: SLF001 (test boundary)

    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    engine = _engine(pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_name() -> None:
    pr = _StatefulBrewRunner()
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="bad name"), process_runner=pr
    )

    engine = _engine(pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_halts_on_brew_install_failure() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list", "--formula", "ripgrep"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("brew", "install", "ripgrep"),
        ProcessResult(
            exit_code=1, stdout="", stderr="boom", duration_ms=0
        ),
    )
    changer = BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )

    engine = _engine(pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    report_result = result.reports[0].result
    assert report_result is not None
    assert report_result.code == "BREW_INSTALL_FAILED"
