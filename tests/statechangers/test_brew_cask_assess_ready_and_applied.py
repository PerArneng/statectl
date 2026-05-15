from __future__ import annotations

import pytest

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import BrewCaskParameters, BrewCaskStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(
    pr: ScriptedProcessRunner,
    *,
    name: str = "google-chrome",
    version: str | None = None,
    tap: str | None = None,
) -> BrewCaskStateChanger:
    return BrewCaskStateChanger(
        BrewCaskParameters(name=name, version=version, tap=tap),
        process_runner=pr,
    )


def _pr_with_brew(
    list_result: ProcessResult,
    info_result: ProcessResult | None = None,
) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(("brew", "list"), list_result)
    if info_result is not None:
        pr.register(("brew", "info"), info_result)
    return pr


@pytest.mark.parametrize(
    "list_stdout, requested_version, expected",
    [
        # not installed, cask known → READY
        ("", None, ExistingState.READY),
        # installed, no version requested → ALREADY_APPLIED
        ("google-chrome 121.0.6167.85\n", None, ExistingState.ALREADY_APPLIED),
        # installed at matching version → ALREADY_APPLIED
        ("google-chrome 1.2.3\n", "1.2.3", ExistingState.ALREADY_APPLIED),
    ],
    ids=["not-installed", "installed-no-version-req", "installed-matching-version"],
)
def test_ready_and_applied_truth_table(
    list_stdout: str, requested_version: str | None, expected: ExistingState
) -> None:
    list_exit = 0 if list_stdout.strip() else 1
    pr = _pr_with_brew(
        ProcessResult(exit_code=list_exit, stdout=list_stdout, stderr="", duration_ms=0),
        ProcessResult(exit_code=0, stdout="info", stderr="", duration_ms=0),
    )
    assessment = _changer(pr, version=requested_version).assess_state()

    assert assessment.state is expected


def test_ready_when_tap_qualified_and_cask_known() -> None:
    pr = _pr_with_brew(
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
        ProcessResult(exit_code=0, stdout="info", stderr="", duration_ms=0),
    )
    assessment = _changer(pr, name="thing", tap="acme/private").assess_state()

    assert assessment.state is ExistingState.READY
