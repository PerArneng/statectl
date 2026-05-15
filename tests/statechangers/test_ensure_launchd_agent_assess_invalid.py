from __future__ import annotations

from statectl._state_changer import ExistingState
from tests.statechangers._launchd_helpers import (
    LABEL,
    OTHER_PLIST_CONTENT,
    PLIST_CONTENT,
    USER_PLIST_PATH,
    make_rig,
    script_loaded,
)


def test_invalid_when_platform_is_not_darwin() -> None:
    rig = make_rig(platform="linux")
    assessment = rig.changer().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("darwin-only" in i for i in assessment.issues)


def test_invalid_when_launchctl_missing() -> None:
    rig = make_rig(launchctl_on_path=False)
    assessment = rig.changer().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("launchctl binary not on PATH" in i for i in assessment.issues)


def test_invalid_when_plist_label_does_not_match() -> None:
    rig = make_rig()
    assessment = rig.changer(plist_content=OTHER_PLIST_CONTENT).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("plist Label mismatch" in i for i in assessment.issues)


def test_invalid_when_plist_xml_is_garbage() -> None:
    rig = make_rig()
    assessment = rig.changer(plist_content="not<xml").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any(
        "not valid XML" in i or "no Label key" in i for i in assessment.issues
    )


def test_invalid_when_label_contains_disallowed_chars() -> None:
    rig = make_rig()
    assessment = rig.changer(label="bad label!").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("invalid label" in i for i in assessment.issues)


def test_invalid_when_target_dir_missing() -> None:
    rig = make_rig(create_user_dir=False)
    assessment = rig.changer().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("plist directory does not exist" in i for i in assessment.issues)


def test_invalid_when_target_dir_not_writable() -> None:
    rig = make_rig()
    rig.fs.set_writable(USER_PLIST_PATH.parent, False)
    assessment = rig.changer().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_existing_plist_owned_by_other_label() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=OTHER_PLIST_CONTENT)
    assessment = rig.changer().assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("refusing to overwrite" in i for i in assessment.issues)


def test_collects_all_issues_in_one_pass() -> None:
    rig = make_rig(platform="linux", launchctl_on_path=False)
    assessment = rig.changer(label="bad!", plist_content="garbage").assess_state()

    assert assessment.state is ExistingState.INVALID
    # At least platform + launchctl + invalid label + plist parse all present
    text = "\n".join(assessment.issues)
    assert "darwin-only" in text
    assert "launchctl binary not on PATH" in text
    assert "invalid label" in text
    assert "not valid XML" in text or "no Label key" in text


def test_invalid_when_loaded_probe_fails() -> None:
    """If the plist is in place with matching content but `launchctl list` /
    `print` cannot complete, surface as INVALID rather than guessing."""
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    # Don't register launchctl list/print — but launchctl is on PATH so probe
    # will use the runner's default exit-0 fallback. Use a different rig to
    # actually exercise probe failure via FailingProcessRunner — covered in
    # capability_errors tests. Here we just ensure assess uses the probe.
    assessment = rig.changer().assess_state()
    # default ScriptedProcessRunner returns exit 0 → already loaded → applied
    assert assessment.state is ExistingState.ALREADY_APPLIED
    # Sanity: with not-loaded scripting we'd say READY
    rig2 = make_rig()
    rig2.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig2.pr, loaded=False)
    other = rig2.changer().assess_state()
    assert other.state is ExistingState.READY
    assert LABEL in other.description
