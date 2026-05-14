from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import FsIoError
from statectl._statechangers import (
    EnsureDirectoryParameters,
    EnsureDirectoryStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def test_assess_does_not_invoke_raising_capability_methods() -> None:
    inner = InMemoryFileSystem()
    inner.add_dir(Path("/work"))
    fs = FailingFileSystem(inner)

    # Stage failures on every raising action method. Assess must not touch them.
    target = Path("/work/data")
    for method in (
        "read_text_file",
        "write_text_file",
        "delete_file",
        "list_files",
        "create_folder",
        "delete_folder",
        "chmod",
    ):
        fs.fail(method, FsIoError("should not be called", path=target), path=target)

    changer = EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=target),
        file_system=fs,
    )
    rollback = changer.rollback()

    # Neither forward nor rollback assess should raise.
    changer.assess_state()
    rollback.assess_state()
