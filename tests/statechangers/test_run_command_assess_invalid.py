from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(
    pr: ScriptedProcessRunner,
    fs: InMemoryFileSystem,
    **overrides: object,
) -> RunCommandStateChanger:
    base: dict[str, object] = {"argv": ("echo", "hi")}
    base.update(overrides)
    return RunCommandStateChanger(
        RunCommandParameters(**base),  # type: ignore[arg-type]
        process_runner=pr,
        file_system=fs,
    )


def test_invalid_when_argv_is_empty() -> None:
    pr = ScriptedProcessRunner()
    fs = InMemoryFileSystem()
    changer = _changer(pr, fs, argv=())

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("argv is empty" in i for i in assessment.issues)


def test_invalid_when_executable_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # nothing registered
    fs = InMemoryFileSystem()
    changer = _changer(pr, fs, argv=("nope",))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("executable not found on PATH" in i for i in assessment.issues)


def test_invalid_when_cwd_does_not_exist() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    fs = InMemoryFileSystem()
    changer = _changer(pr, fs, cwd=Path("/missing"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cwd does not exist" in i for i in assessment.issues)


def test_invalid_when_cwd_is_a_file_not_a_dir() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/notadir"), content="")
    changer = _changer(pr, fs, cwd=Path("/work/notadir"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cwd is not a directory" in i for i in assessment.issues)


def test_invalid_collects_all_issues_in_one_pass() -> None:
    """When multiple preconditions fail, every issue must appear in the
    assessment so callers see the full picture at once.
    """
    pr = ScriptedProcessRunner()  # executable unregistered
    fs = InMemoryFileSystem()  # cwd missing
    changer = _changer(pr, fs, argv=("missing-bin",), cwd=Path("/no/such/dir"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("executable not found on PATH" in i for i in assessment.issues)
    assert any("cwd does not exist" in i for i in assessment.issues)


def test_invalid_collects_empty_argv_and_missing_cwd_together() -> None:
    pr = ScriptedProcessRunner()
    fs = InMemoryFileSystem()
    changer = _changer(pr, fs, argv=(), cwd=Path("/missing"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("argv is empty" in i for i in assessment.issues)
    assert any("cwd does not exist" in i for i in assessment.issues)
