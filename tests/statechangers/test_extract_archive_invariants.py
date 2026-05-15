from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from statectl._interfaces.archive import ArchiveFormat
from statectl._state_changer import (
    Parameters,
    RollbackableStateChanger,
    StateChanger,
)
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive


def _changer(
    fs: InMemoryFileSystem,
    archive: ScriptedArchive,
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


def test_parameters_is_a_frozen_parameters_subclass() -> None:
    params = ExtractArchiveParameters(
        archive_path=Path("/p.tar"),
        dest_dir=Path("/d"),
        format=ArchiveFormat.TAR,
        sentinel_path=Path("/d/x"),
    )
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.dest_dir = Path("/y")  # pyrefly: ignore  # noqa: F841


def test_extract_archive_is_not_rollbackable() -> None:
    changer = _changer(InMemoryFileSystem(), ScriptedArchive())
    assert isinstance(changer, StateChanger)
    assert not isinstance(changer, RollbackableStateChanger)


def test_name_contains_paths() -> None:
    changer = _changer(InMemoryFileSystem(), ScriptedArchive())
    n = changer.name()
    assert "pkg.tar.gz" in n
    assert "out" in n


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/pkg.tar.gz"), content="archive-bytes")
    archive = ScriptedArchive()
    snapshot = dict(fs._nodes)

    _changer(fs, archive).assess_state()

    assert fs._nodes == snapshot
    assert archive.calls == []


def test_assess_state_is_pure_when_called_repeatedly() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/pkg.tar.gz"), content="x")
    changer = _changer(fs, ScriptedArchive())

    first = changer.assess_state()
    second = changer.assess_state()

    assert first.state is second.state
