from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(fs: InMemoryFileSystem) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_first_run_creates_then_second_run_is_skipped() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    target = Path("/work/data")

    engine1 = _engine(fs)
    engine1.add(
        EnsureDirectoryStateChanger(
            EnsureDirectoryParameters(path=target),
            file_system=fs,
        )
    )
    result1 = engine1.start(max_workers=1)
    assert fs.is_dir(target)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in result1.reports)

    engine2 = _engine(fs)
    engine2.add(
        EnsureDirectoryStateChanger(
            EnsureDirectoryParameters(path=target),
            file_system=fs,
        )
    )
    result2 = engine2.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in result2.reports)


def test_engine_halts_on_invalid_assessment() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/data"), content="x")  # path occupied by a file

    engine = _engine(fs)
    engine.add(
        EnsureDirectoryStateChanger(
            EnsureDirectoryParameters(path=Path("/work/data")),
            file_system=fs,
        )
    )
    result = engine.start(max_workers=1)

    assert any(r.outcome is NodeOutcome.FAILED_INVALID for r in result.reports)
    # the existing file is untouched
    assert fs.is_file(Path("/work/data"))


def test_creates_intermediate_directories_when_parents_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    engine = _engine(fs)
    engine.add(
        EnsureDirectoryStateChanger(
            EnsureDirectoryParameters(path=Path("/work/a/b/c"), parents=True),
            file_system=fs,
        )
    )
    engine.start(max_workers=1)

    assert fs.is_dir(Path("/work/a/b/c"))
