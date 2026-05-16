from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    CopyFileParameters,
    CopyFileStateChanger,
)
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


SRC = Path("/work/a")
DEST = Path("/work/b")


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


def _changer(fs: InMemoryFileSystem) -> CopyFileStateChanger:
    return CopyFileStateChanger(
        CopyFileParameters(src=SRC, dest=DEST),
        file_system=fs,
    )


def test_first_run_copies_then_second_run_skips() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hi\n")

    e1 = _engine(fs)
    e1.add(_changer(fs))
    r1 = e1.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in r1.reports)
    assert fs.read_text_file(DEST) == "hi\n"

    e2 = _engine(fs)
    e2.add(_changer(fs))
    r2 = e2.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in r2.reports)


def test_engine_halts_on_invalid_missing_src() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    e = _engine(fs)
    e.add(_changer(fs))
    r = e.start(max_workers=1)
    assert any(rep.outcome is NodeOutcome.FAILED_INVALID for rep in r.reports)


def test_factory_copy_file_routes_through_engine() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(SRC, content="hi\n")
    engine = StateCtl.new(file_system=fs, process_runner=ScriptedProcessRunner())

    changer = engine.changers().copy_file("/work/a", "/work/b", mode=0o600)
    assert isinstance(changer, CopyFileStateChanger)
    assert changer.params.src == SRC
    assert changer.params.dest == DEST
    assert changer.params.mode == 0o600
    assert changer.params.overwrite is False
    assert changer.params.preserve_mtime is False

    engine.add(changer)
    engine.start(max_workers=1)
    assert fs.read_text_file(DEST) == "hi\n"
    assert fs.stat_mode(DEST) == 0o600


def test_factory_copy_file_passes_overwrite_and_preserve_mtime() -> None:
    fs = InMemoryFileSystem()
    engine = StateCtl.new(file_system=fs, process_runner=ScriptedProcessRunner())

    changer = engine.changers().copy_file(
        "/work/a", "/work/b", overwrite=True, preserve_mtime=True
    )
    assert changer.params.overwrite is True
    assert changer.params.preserve_mtime is True
