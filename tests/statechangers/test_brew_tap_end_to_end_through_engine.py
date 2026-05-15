from __future__ import annotations

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._statechangers import BrewTapParameters, BrewTapStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


TAP = "homebrew/cask-fonts"


def _pr() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def test_engine_skips_when_tap_already_present() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=0, stdout=f"{TAP}\n", stderr="", duration_ms=1),
    )
    ctl = StateCtl.new(process_runner=pr)
    ctl.add(BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr))

    result = ctl.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_runs_brew_tap_and_succeeds() -> None:
    # The engine re-assesses after a successful transition. We need the
    # tap-list response to change from "not tapped" to "tapped" once the
    # transition runs. Wrap ScriptedProcessRunner in a tiny stateful shim.
    from typing import Mapping, Sequence, override
    from pathlib import Path

    class _StatefulPR(ScriptedProcessRunner):
        tapped: bool = False

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
            if argv_tuple == ("brew", "tap", TAP):
                self.tapped = True
                return ProcessResult(
                    exit_code=0, stdout="Tapped!", stderr="", duration_ms=10
                )
            if argv_tuple == ("brew", "tap"):
                stdout = f"{TAP}\n" if self.tapped else "other/tap\n"
                return ProcessResult(
                    exit_code=0, stdout=stdout, stderr="", duration_ms=1
                )
            return super().run(
                argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout
            )

    pr = _StatefulPR()
    pr.register_executable("brew")
    ctl = StateCtl.new(process_runner=pr)
    ctl.add(BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr))

    result = ctl.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_halts_on_invalid_when_brew_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # brew not registered
    ctl = StateCtl.new(process_runner=pr)
    ctl.add(BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr))

    result = ctl.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_marks_failed_transition_on_nonzero_exit() -> None:
    pr = _pr()
    pr.register(
        ("brew", "tap", TAP),
        ProcessResult(exit_code=1, stdout="", stderr="bad", duration_ms=5),
    )
    pr.register(
        ("brew", "tap"),
        ProcessResult(exit_code=0, stdout="other/tap\n", stderr="", duration_ms=1),
    )
    ctl = StateCtl.new(process_runner=pr)
    ctl.add(BrewTapStateChanger(BrewTapParameters(name=TAP), process_runner=pr))

    result = ctl.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    report_result = result.reports[0].result
    assert report_result is not None
    assert report_result.code == "BREW_TAP_FAILED"
