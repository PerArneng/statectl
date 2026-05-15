from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[
    InMemoryFileSystem,
    ScriptedProcessRunner,
    ScriptedHttpClient,
    ScriptedEnv,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    pr = ScriptedProcessRunner()
    pr.register_executable("bash")
    http = ScriptedHttpClient()
    env = ScriptedEnv.darwin()
    return fs, pr, http, env


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    http: ScriptedHttpClient,
    env: ScriptedEnv,
    *,
    brew_prefix: Path = Path("/opt/homebrew"),
    accept_eula: bool = True,
) -> EnsureHomebrewInstalledStateChanger:
    return EnsureHomebrewInstalledStateChanger(
        EnsureHomebrewInstalledParameters(
            brew_prefix=brew_prefix,
            accept_eula=accept_eula,
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=env,
    )


def test_is_a_state_changer() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    assert isinstance(changer, StateChanger)


def test_is_not_rollbackable() -> None:
    """Documents the design: uninstalling brew is destructive; no inverse."""
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    assert not isinstance(changer, RollbackableStateChanger)


def test_parameters_are_frozen() -> None:
    params = EnsureHomebrewInstalledParameters(brew_prefix=Path("/opt/homebrew"))

    with pytest.raises(Exception):
        params.brew_prefix = Path("/usr/local")  # type: ignore[misc]


def test_name_encodes_prefix() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env, brew_prefix=Path("/opt/homebrew"))

    assert changer.name() == "ensure-homebrew-installed:/opt/homebrew"


def test_assess_state_does_not_invoke_http_or_process() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    changer.assess_state()
    changer.assess_state()

    assert http.calls == []
    assert pr.calls == []


def test_assess_state_does_not_mutate_filesystem() -> None:
    fs, pr, http, env = _rig()
    changer = _changer(fs, pr, http, env)

    before = set(fs._nodes.keys())  # noqa: SLF001 (test boundary)
    changer.assess_state()
    after = set(fs._nodes.keys())  # noqa: SLF001

    assert before == after
