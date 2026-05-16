from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import DeletePathParameters, DeletePathStateChanger
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
        variable_registry=InMemoryVariableRegistry(),
    )


def test_first_run_deletes_then_second_run_skips() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/f"))

    e1 = _engine(fs)
    e1.add(
        DeletePathStateChanger(
            DeletePathParameters(path=Path("/work/f"), kind="file"),
            file_system=fs,
        )
    )
    r1 = e1.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in r1.reports)
    assert not fs.exists(Path("/work/f"))

    e2 = _engine(fs)
    e2.add(
        DeletePathStateChanger(
            DeletePathParameters(path=Path("/work/f"), kind="file", missing_ok=True),
            file_system=fs,
        )
    )
    r2 = e2.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in r2.reports)


def test_engine_halts_on_invalid_kind_mismatch() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/d"))

    e = _engine(fs)
    e.add(
        DeletePathStateChanger(
            DeletePathParameters(path=Path("/work/d"), kind="file"),
            file_system=fs,
        )
    )
    r = e.start(max_workers=1)
    assert any(rep.outcome is NodeOutcome.FAILED_INVALID for rep in r.reports)
    assert fs.is_dir(Path("/work/d"))
