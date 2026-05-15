from __future__ import annotations

from pathlib import Path

from statectl import NodeOutcome, StateCtl
from statectl._interfaces.archive import ArchiveFormat
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(
    file_system: InMemoryFileSystem,
    archive: ScriptedArchive,
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=file_system,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=archive,
        variable_registry=InMemoryVariableRegistry(),
    )


def _changer(
    fs: InMemoryFileSystem, archive: ScriptedArchive
) -> ExtractArchiveStateChanger:
    return ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=Path("/pkg.tar.gz"),
            dest_dir=Path("/work/out"),
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=Path("/work/out/bin/foo"),
        ),
        file_system=fs,
        archive=archive,
    )


def test_engine_extracts_then_skips_on_second_run_via_sentinel() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/pkg.tar.gz"), content="bytes")
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(
        Path("/pkg.tar.gz"),
        ArchiveFormat.TAR_GZ,
        entries={"bin/foo": "binary"},
    )

    engine = _engine(fs, archive)
    engine.add(_changer(fs, archive))
    result = engine.start(max_workers=1)

    assert all(r.outcome is NodeOutcome.SUCCESS for r in result.reports)
    assert len(archive.calls) == 1

    # Second run: sentinel exists, no second extract.
    engine2 = _engine(fs, archive)
    engine2.add(_changer(fs, archive))
    result2 = engine2.start(max_workers=1)
    assert all(
        r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in result2.reports
    )
    assert len(archive.calls) == 1


def test_engine_marks_failed_invalid_when_archive_missing() -> None:
    fs = InMemoryFileSystem()
    archive = ScriptedArchive(file_system=fs)

    engine = _engine(fs, archive)
    engine.add(_changer(fs, archive))
    result = engine.start(max_workers=1)

    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
    assert archive.calls == []
