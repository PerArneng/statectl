from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    SetFileModeParameters,
    SetFileModeStateChanger,
)
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.fakes.scripted_clock import ScriptedClock


def _engine(fs: InMemoryFileSystem) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _changer(fs: InMemoryFileSystem, path: Path, mode: int) -> SetFileModeStateChanger:
    return SetFileModeStateChanger(
        SetFileModeParameters(path=path, mode=mode),
        file_system=fs,
    )


def test_first_run_chmods_then_second_run_skips() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o600)

    e1 = _engine(fs)
    e1.add(_changer(fs, Path("/work/x"), 0o644))
    r1 = e1.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in r1.reports)
    assert fs.stat_mode(Path("/work/x")) == 0o644

    e2 = _engine(fs)
    e2.add(_changer(fs, Path("/work/x"), 0o644))
    r2 = e2.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in r2.reports)


def test_engine_halts_on_invalid_missing_path() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))

    e = _engine(fs)
    e.add(_changer(fs, Path("/work/missing"), 0o644))
    r = e.start(max_workers=1)
    assert any(rep.outcome is NodeOutcome.FAILED_INVALID for rep in r.reports)


def test_factory_set_file_mode_routes_through_engine() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/x"), mode=0o600)
    engine = StateCtl.new(file_system=fs, process_runner=ScriptedProcessRunner())

    changer = engine.changers().set_file_mode("/work/x", 0o755)
    assert isinstance(changer, SetFileModeStateChanger)
    assert changer.params.path == Path("/work/x")
    assert changer.params.mode == 0o755
    assert changer.params.follow_symlinks is True

    engine.add(changer)
    engine.start(max_workers=1)
    assert fs.stat_mode(Path("/work/x")) == 0o755


def test_factory_set_file_mode_passes_follow_symlinks() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    engine = StateCtl.new(file_system=fs, process_runner=ScriptedProcessRunner())

    changer = engine.changers().set_file_mode("/work/lnk", 0o700, follow_symlinks=False)
    assert changer.params.follow_symlinks is False
