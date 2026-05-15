from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl import StateCtl
from statectl._statechangers import (
    RunCommandParameters,
    RunCommandStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(
    file_system: InMemoryFileSystem | None = None,
    process_runner: ScriptedProcessRunner | None = None,
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=file_system or InMemoryFileSystem(),
        process_runner=process_runner or ScriptedProcessRunner(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_engine_runs_command_then_skips_on_second_run_via_creates_hint() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("touch")
    pr.register(("touch",), ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0))
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    marker = Path("/work/marker")

    # First engine run: no marker yet, command runs, then we simulate side
    # effect by creating the marker (the real touch would do this).
    engine1 = _engine()
    engine1.add(
        RunCommandStateChanger(
            RunCommandParameters(argv=("touch", str(marker)), creates=marker),
            process_runner=pr,
            file_system=fs,
        )
    )
    engine1.start(max_workers=1)
    assert len(pr.calls) == 1

    # Simulate that the command produced the artifact.
    fs.add_file(marker, content="")

    # Second engine run: marker exists, assess returns ALREADY_APPLIED, skip.
    engine2 = _engine()
    engine2.add(
        RunCommandStateChanger(
            RunCommandParameters(argv=("touch", str(marker)), creates=marker),
            process_runner=pr,
            file_system=fs,
        )
    )
    engine2.start(max_workers=1)
    assert len(pr.calls) == 1  # no new call


def test_engine_halts_on_failure_and_does_not_run_subsequent_changers() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("fails")
    pr.register_executable("never")
    pr.register(
        ("fails",), ProcessResult(exit_code=1, stdout="", stderr="bad", duration_ms=0)
    )
    pr.register(
        ("never",), ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
    )
    fs = InMemoryFileSystem()

    failing = RunCommandStateChanger(
        RunCommandParameters(argv=("fails",)),
        process_runner=pr,
        file_system=fs,
    )
    after = RunCommandStateChanger(
        RunCommandParameters(argv=("never",)),
        process_runner=pr,
        file_system=fs,
    )

    engine = _engine()
    engine.add(failing)
    engine.add(after, depends_on=[failing])
    engine.start(max_workers=1)

    argvs = [c.argv for c in pr.calls]
    assert ("fails",) in argvs
    assert ("never",) not in argvs


def test_engine_halts_on_invalid_assessment() -> None:
    pr = ScriptedProcessRunner()  # nothing registered → which returns None
    fs = InMemoryFileSystem()

    invalid = RunCommandStateChanger(
        RunCommandParameters(argv=("missing-bin",)),
        process_runner=pr,
        file_system=fs,
    )

    engine = _engine()
    engine.add(invalid)
    engine.start(max_workers=1)

    # transition was never called because assess returned INVALID
    assert pr.calls == []
