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
    EnsureDirectoryParameters,
    EnsureDirectoryRollbackStateChanger,
    EnsureDirectoryStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem


def _changer(fs: InMemoryFileSystem) -> EnsureDirectoryStateChanger:
    return EnsureDirectoryStateChanger(
        EnsureDirectoryParameters(path=Path("/work/data")),
        file_system=fs,
    )


def test_parameters_is_a_frozen_parameters_subclass() -> None:
    params = EnsureDirectoryParameters(path=Path("/x"))
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.path = Path("/y")  # pyrefly: ignore  # noqa: F841


def test_forward_extends_rollbackable_and_inverse_is_plain() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs)

    assert isinstance(changer, RollbackableStateChanger)
    rollback = changer.rollback()
    assert isinstance(rollback, StateChanger)
    assert isinstance(rollback, EnsureDirectoryRollbackStateChanger)
    assert not isinstance(rollback, RollbackableStateChanger)


def test_name_contains_path_for_both_directions() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs)
    rollback = changer.rollback()

    assert str(Path("/work/data")) in changer.name()
    assert str(Path("/work/data")) in rollback.name()
    assert changer.name() != rollback.name()


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    snapshot = dict(fs._nodes)
    _changer(fs).assess_state()

    assert fs._nodes == snapshot


def test_assess_state_is_pure_when_called_repeatedly() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    changer = _changer(fs)

    first = changer.assess_state()
    second = changer.assess_state()

    assert first.state is second.state


def test_transition_writes_through_injected_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    result = _changer(fs).transition()

    assert result.status is ResultStatus.SUCCESS
    assert fs.is_dir(Path("/work/data"))


def test_already_applied_assessment_has_no_issues() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(Path("/work/data"))

    assessment = _changer(fs).assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED
    assert assessment.issues == []
