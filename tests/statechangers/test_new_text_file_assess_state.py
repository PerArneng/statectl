from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, RollbackableStateChanger
from statectl._statechangers import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem | FailingFileSystem, path: Path, text: str) -> RollbackableStateChanger:
    return NewTextFileStateChanger(
        NewTextFileParameters(path=path, text=text),
        file_system=fs,
    )


def test_ready_when_parent_dir_exists_and_target_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.READY
    assert assessment.issues == []


def test_already_applied_when_file_has_desired_content() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/hello.txt"), content="hi")
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_invalid_when_parent_directory_missing() -> None:
    fs = InMemoryFileSystem()
    changer = _changer(fs, Path("/missing/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("parent directory does not exist" in i for i in assessment.issues)


def test_invalid_when_parent_is_not_a_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/parent"), content="")
    changer = _changer(fs, Path("/work/parent/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not a directory" in i for i in assessment.issues)


def test_invalid_when_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"), writable=False)
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_target_exists_as_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/hello.txt"))
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in assessment.issues)


def test_invalid_when_existing_file_has_different_content() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/hello.txt"), content="other")
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert assessment.issues == ["file exists with different content"]


def test_invalid_when_existing_file_cannot_be_decoded() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/hello.txt"), content="hi", readable_text=False)
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cannot read existing file" in i for i in assessment.issues)


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs, Path("/work/hello.txt"), "hi")

    changer.assess_state()

    assert not fs.exists(Path("/work/hello.txt"))
