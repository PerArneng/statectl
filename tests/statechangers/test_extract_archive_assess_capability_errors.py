from __future__ import annotations

from pathlib import Path

from statectl._interfaces.archive import ArchiveError, ArchiveFormat
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)
from tests.fakes.failing_archive import FailingArchive
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive


ARCHIVE = Path("/work/pkg.tar.gz")
DEST = Path("/work/out")
SENTINEL = Path("/work/out/bin/foo")


def test_assess_does_not_invoke_archive_action_methods() -> None:
    inner = ScriptedArchive()
    inner.register_archive(ARCHIVE, ArchiveFormat.TAR_GZ)
    wrapper = FailingArchive(inner)
    # If assess ever calls extract, this would raise and the test would error.
    wrapper.fail("extract", ArchiveError("must not be called"))

    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(ARCHIVE, content="ar")
    fs.add_dir(DEST)

    changer = ExtractArchiveStateChanger(
        ExtractArchiveParameters(
            archive_path=ARCHIVE,
            dest_dir=DEST,
            format=ArchiveFormat.TAR_GZ,
            sentinel_path=SENTINEL,
        ),
        file_system=fs,
        archive=wrapper,
    )

    # Must not raise — assess uses only non-raising fs queries.
    changer.assess_state()
    assert len(inner.calls) == 0
