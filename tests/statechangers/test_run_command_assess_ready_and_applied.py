from __future__ import annotations

from pathlib import Path

import pytest

from statectl.state_changer import ExistingState
from statectl.statechangers.run_command import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


CREATES = Path("/work/output")
REMOVES = Path("/work/sentinel")


def _rig(*, creates_exists: bool, removes_exists: bool) -> tuple[ScriptedProcessRunner, InMemoryFileSystem]:
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    if creates_exists:
        fs.add_file(CREATES, content="x")
    if removes_exists:
        fs.add_file(REMOVES, content="x")
    return pr, fs


def _changer(
    pr: ScriptedProcessRunner,
    fs: InMemoryFileSystem,
    *,
    creates: Path | None = None,
    removes: Path | None = None,
) -> RunCommandStateChanger:
    return RunCommandStateChanger(
        RunCommandParameters(argv=("echo", "hi"), creates=creates, removes=removes),
        process_runner=pr,
        file_system=fs,
    )


def test_ready_when_no_hints_set() -> None:
    pr, fs = _rig(creates_exists=False, removes_exists=False)
    assessment = _changer(pr, fs).assess_state()
    assert assessment.state is ExistingState.READY


@pytest.mark.parametrize(
    "creates_set, creates_exists, removes_set, removes_exists, expected",
    [
        # creates only
        (True, True, False, False, ExistingState.ALREADY_APPLIED),
        (True, False, False, False, ExistingState.READY),
        # removes only
        (False, False, True, False, ExistingState.ALREADY_APPLIED),
        (False, False, True, True, ExistingState.READY),
        # both — both must indicate "applied" for skip
        (True, True, True, False, ExistingState.ALREADY_APPLIED),
        (True, True, True, True, ExistingState.READY),
        (True, False, True, False, ExistingState.READY),
        (True, False, True, True, ExistingState.READY),
    ],
)
def test_idempotency_truth_table(
    creates_set: bool,
    creates_exists: bool,
    removes_set: bool,
    removes_exists: bool,
    expected: ExistingState,
) -> None:
    pr, fs = _rig(creates_exists=creates_exists, removes_exists=removes_exists)
    changer = _changer(
        pr,
        fs,
        creates=CREATES if creates_set else None,
        removes=REMOVES if removes_set else None,
    )

    assessment = changer.assess_state()

    assert assessment.state is expected
