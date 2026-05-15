from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from statectl._state_changer import (
    ExistingState,
    Parameters,
    ResultStatus,
    RollbackableStateChanger,
    StateChanger,
)
from statectl._statechangers import (
    EnsureSymlinkParameters,
    EnsureSymlinkRollbackStateChanger,
    EnsureSymlinkStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem) -> EnsureSymlinkStateChanger:
    return EnsureSymlinkStateChanger(
        EnsureSymlinkParameters(link_path=Path("/work/link"), target=Path("/work/target")),
        file_system=fs,
    )


def test_parameters_is_a_frozen_parameters_subclass() -> None:
    params = EnsureSymlinkParameters(link_path=Path("/x"), target=Path("/y"))
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.link_path = Path("/z")  # pyrefly: ignore  # noqa: F841


def test_forward_extends_rollbackable_and_inverse_is_plain() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs)

    assert isinstance(changer, RollbackableStateChanger)
    rollback = changer.rollback()
    assert isinstance(rollback, StateChanger)
    assert isinstance(rollback, EnsureSymlinkRollbackStateChanger)
    assert not isinstance(rollback, RollbackableStateChanger)


def test_name_contains_link_path_for_both_directions() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs)
    rollback = changer.rollback()

    assert str(Path("/work/link")) in changer.name()
    assert str(Path("/work/link")) in rollback.name()
    assert changer.name() != rollback.name()


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    snapshot = dict(fs._nodes)
    _changer(fs).assess_state()

    assert fs._nodes == snapshot


def test_transition_creates_symlink_pointing_at_target() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/target"), content="hi")

    result = _changer(fs).transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_symlink(Path("/work/link"))
    assert fs.read_symlink(Path("/work/link")) == Path("/work/target")


def test_second_assess_after_apply_is_already_applied() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/target"), content="hi")
    changer = _changer(fs)

    changer.transition()
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED
    assert assessment.issues == []
