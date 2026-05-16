from __future__ import annotations

from pathlib import Path

from statectl._engine_result import NodeOutcome
from statectl._interfaces.archive import ArchiveFormat
from statectl._modules import (
    DefaultLogger,
    InMemoryVariableRegistry,
)
from statectl._state_changer import (
    ExistingState,
    Result,
    StateAssessment,
    StateChanger,
)
from statectl.state_ctl import StateCtl
from typing import override
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_hashing import ScriptedHashing
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


ARCHIVE = Path("/work/pkg.tar.gz")
DEST = Path("/work/out")
SENTINEL = Path("/work/out/bin/foo")


def _engine(fs: InMemoryFileSystem, archive: ScriptedArchive) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=archive,
        hashing=ScriptedHashing(file_system=fs),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="ar")
    fs.add_dir(DEST)
    return fs


def test_engine_runs_extract_to_success() -> None:
    fs = _fs()
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(
        ARCHIVE, ArchiveFormat.TAR_GZ, entries={"bin/foo": "x"}
    )
    ctl = _engine(fs, archive)
    sc = ctl.changers()
    node = sc.extract_archive(ARCHIVE, DEST, ArchiveFormat.TAR_GZ, SENTINEL)
    ctl.add(node)
    result = ctl.start()
    assert any(r.outcome is NodeOutcome.SUCCESS for r in result.reports)


def test_engine_skips_when_sentinel_already_exists() -> None:
    fs = _fs()
    fs.add_dir(DEST / "bin")
    fs.add_file(SENTINEL, content="already there")
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(ARCHIVE, ArchiveFormat.TAR_GZ)
    ctl = _engine(fs, archive)
    sc = ctl.changers()
    node = sc.extract_archive(ARCHIVE, DEST, ArchiveFormat.TAR_GZ, SENTINEL)
    ctl.add(node)
    result = ctl.start()
    assert any(
        r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in result.reports
    )
    assert archive.calls == []


def test_engine_halts_on_invalid_when_archive_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(DEST)
    archive = ScriptedArchive(file_system=fs)
    ctl = _engine(fs, archive)
    sc = ctl.changers()
    node = sc.extract_archive(ARCHIVE, DEST, ArchiveFormat.TAR_GZ, SENTINEL)
    ctl.add(node)
    result = ctl.start()
    assert any(r.outcome is NodeOutcome.FAILED_INVALID for r in result.reports)
