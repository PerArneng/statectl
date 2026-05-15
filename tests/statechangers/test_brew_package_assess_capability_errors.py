from __future__ import annotations

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessTimeout,
)
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    BrewPackageParameters,
    BrewPackageStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(pr: FailingProcessRunner) -> BrewPackageStateChanger:
    return BrewPackageStateChanger(
        BrewPackageParameters(name="ripgrep"), process_runner=pr
    )


def _inner() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    pr.register(
        ("brew", "list", "--formula", "ripgrep"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    return pr


def test_assess_does_not_raise_on_process_not_found() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessNotFound("missing", argv=("brew",)))
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("not found" in i for i in assess.issues)


def test_assess_does_not_raise_on_process_timeout() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessTimeout("timed out", argv=("brew",)))
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("timed out" in i for i in assess.issues)


def test_assess_does_not_raise_on_process_decode_error() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessDecodeError("decode failed", argv=("brew",)))
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("decode" in i for i in assess.issues)


def test_assess_does_not_raise_on_process_launch_error() -> None:
    pr = FailingProcessRunner(_inner())
    pr.fail("run", ProcessLaunchError("launch failed", argv=("brew",)))
    changer = _changer(pr)

    assess = changer.assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("launch" in i for i in assess.issues)
