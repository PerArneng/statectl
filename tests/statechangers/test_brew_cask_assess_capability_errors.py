from __future__ import annotations

from statectl._interfaces.process import ProcessLaunchError, ProcessTimeout
from statectl._state_changer import ExistingState
from statectl._statechangers import BrewCaskParameters, BrewCaskStateChanger
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(pr: ScriptedProcessRunner | FailingProcessRunner) -> BrewCaskStateChanger:
    return BrewCaskStateChanger(
        BrewCaskParameters(name="google-chrome"),
        process_runner=pr,  # type: ignore[arg-type]
    )


def test_process_timeout_in_assess_becomes_invalid_issue() -> None:
    """assess_state must not raise process errors — it converts them to issues
    so the engine can present a clean INVALID verdict to the driver.
    """
    inner = ScriptedProcessRunner()
    inner.register_executable("brew")
    pr = FailingProcessRunner(inner)
    pr.fail("run", ProcessTimeout("too long"))

    assessment = _changer(pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("failed to query installed cask" in i for i in assessment.issues)


def test_process_launch_error_in_assess_becomes_invalid_issue() -> None:
    inner = ScriptedProcessRunner()
    inner.register_executable("brew")
    pr = FailingProcessRunner(inner)
    pr.fail("run", ProcessLaunchError("os boom"))

    assessment = _changer(pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("failed to query installed cask" in i for i in assessment.issues)
