from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    AptRepositoryParameters,
    AptRepositoryStateChanger,
    InlineKey,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


FP = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"


def _rig() -> tuple[
    InMemoryFileSystem,
    ScriptedProcessRunner,
    ScriptedHttpClient,
    ScriptedEnv,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/apt"))
    fs.add_dir(Path("/etc/apt/sources.list.d"))
    fs.add_dir(Path("/etc/apt/keyrings"))
    pr = ScriptedProcessRunner()
    pr.register_executable("gpg")
    http = ScriptedHttpClient()
    env = ScriptedEnv.linux()
    return fs, pr, http, env


def _params() -> AptRepositoryParameters:
    return AptRepositoryParameters(
        name="docker",
        uri="https://download.docker.com/linux/ubuntu",
        suite="jammy",
        components=("stable",),
        signing_key=InlineKey(armored="-----BEGIN-----", fingerprint=FP),
    )


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    http: ScriptedHttpClient,
    env: ScriptedEnv,
) -> AptRepositoryStateChanger:
    return AptRepositoryStateChanger(
        _params(),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=env,
    )


def test_is_rollbackable_state_changer() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    assert isinstance(changer, StateChanger)
    assert isinstance(changer, RollbackableStateChanger)


def test_parameters_are_frozen() -> None:
    p = _params()

    with pytest.raises(Exception):
        p.name = "other"  # type: ignore[misc]


def test_name_encodes_repository_name() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    assert changer.name() == "apt-repository:docker"


def test_rollback_returns_inverse_changer() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    inverse = changer.rollback()
    assert isinstance(inverse, StateChanger)
    assert not isinstance(inverse, RollbackableStateChanger)
    assert inverse.name() == "apt-repository-rollback:docker"


def test_assess_state_does_not_invoke_http() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    changer.assess_state()

    assert http.calls == []


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    before = set(fs._nodes.keys())  # noqa: SLF001
    changer.assess_state()
    after = set(fs._nodes.keys())  # noqa: SLF001

    assert before == after
