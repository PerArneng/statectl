from __future__ import annotations

from pathlib import Path

from statectl._interfaces.archive import ArchiveFormat
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import RecordedExtract, ScriptedArchive


ARCHIVE = Path("/work/pkg.tar.gz")
DEST = Path("/work/out")
SENTINEL = Path("/work/out/bin/foo")


def _setup(
    *, with_dest: bool = True, strip_components: int = 0
) -> tuple[InMemoryFileSystem, ScriptedArchive, ExtractArchiveStateChanger]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="ar")
    if with_dest:
        fs.add_dir(DEST)
    archive = ScriptedArchive(file_system=fs)
    archive.register_archive(
        ARCHIVE,
        ArchiveFormat.TAR_GZ,
        entries={"bin/foo": "payload", "README": "readme"},
    )
    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
            strip_components=strip_components,
        ),
        file_system=fs,
        archive=archive,
    )
    return fs, archive, changer


def test_transition_extracts_and_records_call() -> None:
    fs, archive, changer = _setup()
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert archive.calls == [
        RecordedExtract(
            src=ARCHIVE, dest=DEST, format=ArchiveFormat.TAR_GZ, strip_components=0
        )
    ]
    # Files written by scripted archive
    assert fs.read_text_file(DEST / "bin" / "foo") == "payload"
    assert fs.read_text_file(DEST / "README") == "readme"


def test_transition_details_carry_metadata() -> None:
    _fs, _ar, changer = _setup()
    result = changer.transition()
    assert result.details["archive_path"] == str(ARCHIVE)
    assert result.details["dest_dir"] == str(DEST)
    assert result.details["format"] == "tar.gz"
    assert result.details["strip_components"] == "0"


def test_transition_creates_missing_dest_dir() -> None:
    fs, _ar, changer = _setup(with_dest=False)
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert fs.is_dir(DEST)


def test_transition_passes_strip_components_to_archive() -> None:
    _fs, archive, changer = _setup(strip_components=2)
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert archive.calls[0].strip_components == 2


def test_post_assess_returns_already_applied_after_successful_transition() -> None:
    _fs, _ar, changer = _setup()
    changer.transition()
    a = changer.assess_state()
    assert a.state is ExistingState.ALREADY_APPLIED
