from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageRollbackStateChanger,
    AptPackageStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _fs_with_debian_marker() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    return fs


def _rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = _fs_with_debian_marker()
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(binary)
    return fs, pr


def test_is_rollbackable_state_changer() -> None:
    fs, pr = _rig()
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    assert isinstance(changer, RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    fs, pr = _rig()
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    inverse = changer.rollback()

    assert isinstance(inverse, StateChanger)
    assert not isinstance(inverse, RollbackableStateChanger)
    assert isinstance(inverse, AptPackageRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = AptPackageParameters(name="curl")

    with pytest.raises(Exception):
        params.name = "wget"  # type: ignore[misc]


def test_name_encodes_plain_package() -> None:
    fs, pr = _rig()
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    assert changer.name() == "apt-package:curl"


def test_name_encodes_versioned_package() -> None:
    fs, pr = _rig()
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl", version="7.88.1-10+deb12u5"),
        file_system=fs,
        process_runner=pr,
    )

    assert changer.name() == "apt-package:curl=7.88.1-10+deb12u5"


def test_rollback_name_encodes_package() -> None:
    fs, pr = _rig()
    inverse = AptPackageRollbackStateChanger(
        AptPackageParameters(name="curl"), file_system=fs, process_runner=pr
    )

    assert inverse.name() == "apt-package-rollback:curl"
