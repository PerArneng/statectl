from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from statectl._interfaces.archive import ArchiveFormat
from statectl._state_changer import Parameters, StateChanger
from statectl._statechangers import (
    ExtractArchiveParameters,
    ExtractArchiveStateChanger,
)


ARCHIVE = Path("/work/pkg.tar.gz")
DEST = Path("/work/out")
SENTINEL = Path("/work/out/bin/foo")


def _params() -> ExtractArchiveParameters:
    return ExtractArchiveParameters(
        archive_path=ARCHIVE,
        dest_dir=DEST,
        format=ArchiveFormat.TAR_GZ,
        sentinel_path=SENTINEL,
    )


def test_parameters_is_frozen_parameters_subclass() -> None:
    params = _params()
    assert isinstance(params, Parameters)
    with pytest.raises(FrozenInstanceError):
        params.dest_dir = Path("/other")  # type: ignore[misc]


def test_changer_is_plain_state_changer_not_rollbackable() -> None:
    from statectl._state_changer import RollbackableStateChanger

    changer = ExtractArchiveStateChanger(_params())
    assert isinstance(changer, StateChanger)
    assert not isinstance(changer, RollbackableStateChanger)


def test_name_encodes_archive_and_dest() -> None:
    changer = ExtractArchiveStateChanger(_params())
    assert str(ARCHIVE) in changer.name()
    assert str(DEST) in changer.name()


def test_parameters_defaults() -> None:
    params = _params()
    assert params.create_dest is True
    assert params.strip_components == 0
