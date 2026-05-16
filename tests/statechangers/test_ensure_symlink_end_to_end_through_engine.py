from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkStateChanger,
)
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(fs: InMemoryFileSystem) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _params() -> EnsureSymlinkParameters:
    return EnsureSymlinkParameters(
        link_path=Path("/work/link"),
        target=Path("/work/target"),
    )


def test_first_run_creates_then_second_run_skipped() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    engine1 = _engine(fs)
    engine1.add(EnsureSymlinkStateChanger(_params(), file_system=fs))
    result1 = engine1.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in result1.reports)
    assert fs.is_symlink(Path("/work/link"))

    engine2 = _engine(fs)
    engine2.add(EnsureSymlinkStateChanger(_params(), file_system=fs))
    result2 = engine2.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in result2.reports)


def test_engine_halts_on_invalid_assessment() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/link"), content="x")  # not a symlink, no overwrite

    engine = _engine(fs)
    engine.add(EnsureSymlinkStateChanger(_params(), file_system=fs))
    result = engine.start(max_workers=1)

    assert any(r.outcome is NodeOutcome.FAILED_INVALID for r in result.reports)
    assert fs.is_file(Path("/work/link"))
