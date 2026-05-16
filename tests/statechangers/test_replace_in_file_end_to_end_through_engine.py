from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    LiteralMatch,
    ReplaceInFileParameters,
    ReplaceInFileStateChanger,
)
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


P = Path("/w/c.txt")


def _engine(fs: InMemoryFileSystem) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _fs(content: str) -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))
    fs.add_file(P, content=content)
    return fs


def _changer(fs: InMemoryFileSystem) -> ReplaceInFileStateChanger:
    return ReplaceInFileStateChanger(
        ReplaceInFileParameters(
            path=P,
            match=LiteralMatch(needle="foo", expected_count=1, replacement="bar"),
        ),
        file_system=fs,
    )


def test_first_run_substitutes_then_second_run_is_skipped() -> None:
    fs = _fs("foo\n")

    e1 = _engine(fs)
    e1.add(_changer(fs))
    r1 = e1.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in r1.reports)
    assert fs.read_text_file(P) == "bar\n"

    e2 = _engine(fs)
    e2.add(_changer(fs))
    r2 = e2.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in r2.reports)


def test_engine_halts_on_invalid_assessment() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/w"))  # file does not exist
    engine = _engine(fs)
    engine.add(_changer(fs))
    result = engine.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.FAILED_INVALID for r in result.reports)
