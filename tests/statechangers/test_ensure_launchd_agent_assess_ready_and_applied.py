from __future__ import annotations

import pytest

from statectl._state_changer import ExistingState
from tests.statechangers._launchd_helpers import (
    PLIST_CONTENT,
    SYSTEM_PLIST_PATH,
    USER_PLIST_PATH,
    make_rig,
    script_loaded,
)


@pytest.mark.parametrize(
    "scope,plist_path,create_system",
    [
        ("user", USER_PLIST_PATH, False),
        ("system", SYSTEM_PLIST_PATH, True),
    ],
)
def test_ready_when_plist_missing(scope: str, plist_path, create_system: bool) -> None:
    rig = make_rig(create_system_dir=create_system)
    assessment = rig.changer(scope=scope).assess_state()
    assert assessment.state is ExistingState.READY
    assert str(plist_path) in assessment.description


def test_ready_when_plist_present_but_not_loaded() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=False)

    assessment = rig.changer().assess_state()
    assert assessment.state is ExistingState.READY


def test_ready_when_owned_plist_has_drifted_content() -> None:
    """Same Label, different content → READY (we'll rewrite)."""
    rig = make_rig()
    drifted = PLIST_CONTENT.replace("<dict>", "<dict>\n    <!-- drift -->")
    rig.fs.add_file(USER_PLIST_PATH, content=drifted)

    assessment = rig.changer().assess_state()
    assert assessment.state is ExistingState.READY


def test_already_applied_when_plist_matches_and_loaded() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=True)

    assessment = rig.changer().assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_plist_matches_and_loaded_not_required() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    # `loaded=False` skips the launchctl probe entirely
    assessment = rig.changer(loaded=False).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_with_explicit_domain_target() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=True)

    assessment = rig.changer(domain_target="gui/501").assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED
    # Verify the modern probe argv was used
    assert any(
        c.argv == ("launchctl", "print", "gui/501/com.example.foo")
        for c in rig.pr.calls
    )
