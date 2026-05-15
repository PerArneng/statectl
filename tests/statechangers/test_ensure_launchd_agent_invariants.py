from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentRollbackStateChanger,
    EnsureLaunchdAgentStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_PLIST = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<plist version="1.0">\n'
    "  <dict>\n"
    "    <key>Label</key>\n"
    "    <string>com.example.foo</string>\n"
    "  </dict>\n"
    "</plist>\n"
)


def _params(**kw: object) -> EnsureLaunchdAgentParameters:
    defaults: dict[str, object] = dict(
        label="com.example.foo",
        plist_content=_PLIST,
        scope="user",
        loaded=True,
        domain_target=None,
    )
    defaults.update(kw)
    return EnsureLaunchdAgentParameters(**defaults)  # type: ignore[arg-type]


def _changer() -> EnsureLaunchdAgentStateChanger:
    pr = ScriptedProcessRunner()
    pr.register_executable("launchctl")
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/Users/test/Library/LaunchAgents"))
    return EnsureLaunchdAgentStateChanger(
        _params(),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.darwin(),
    )


def test_is_a_rollbackable_state_changer() -> None:
    changer = _changer()
    assert isinstance(changer, RollbackableStateChanger)
    assert isinstance(changer, StateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    changer = _changer()
    rb = changer.rollback()
    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, EnsureLaunchdAgentRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = _params()
    with pytest.raises(Exception):
        params.label = "other"  # type: ignore[misc]


def test_name_encodes_scope_and_label() -> None:
    changer = _changer()
    assert changer.name() == "ensure-launchd-agent:user/com.example.foo"


def test_rollback_name_encodes_scope_and_label() -> None:
    changer = _changer()
    assert (
        changer.rollback().name()
        == "ensure-launchd-agent-rollback:user/com.example.foo"
    )
