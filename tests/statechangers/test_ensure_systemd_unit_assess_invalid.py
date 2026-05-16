from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    HOME,
    USER_UNIT_DIR,
    make_changer,
    make_fs_with_user_unit_dir,
    make_unit_content,
)


def test_invalid_when_platform_is_not_linux() -> None:
    env = ScriptedEnv.darwin(home=HOME)
    assessment = make_changer(env=env).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("Linux-only" in i for i in assessment.issues)


def test_invalid_when_systemctl_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # systemctl NOT registered
    assessment = make_changer(pr=pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("systemctl not on PATH" in i for i in assessment.issues)


def test_invalid_when_unit_suffix_unrecognised() -> None:
    assessment = make_changer(unit_name="myapp.weird").assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("unit suffix unrecognised" in i for i in assessment.issues)


def test_invalid_when_unit_name_empty() -> None:
    assessment = make_changer(unit_name="").assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("unit_name is empty" in i for i in assessment.issues)


def test_invalid_when_unit_content_has_no_section() -> None:
    assessment = make_changer(unit_content="not a unit file at all").assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("no [Section] header" in i for i in assessment.issues)


def test_invalid_when_unit_dir_does_not_exist() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("unit directory does not exist" in i for i in assessment.issues)


def test_invalid_when_unit_dir_not_writable() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.set_writable(USER_UNIT_DIR, False)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_unit_path_is_a_directory() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_dir(USER_UNIT_DIR / DEFAULT_UNIT)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in assessment.issues)


def test_invalid_when_existing_unit_has_different_description() -> None:
    fs = make_fs_with_user_unit_dir()
    other = make_unit_content(description="SomeoneElse daemon")
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=other)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any(
        "different [Unit] Description" in i for i in assessment.issues
    )


def test_ready_when_existing_unit_has_matching_description_but_different_body() -> None:
    # Same Description — counts as "our" unit drifted; READY to overwrite.
    fs = make_fs_with_user_unit_dir()
    drifted = make_unit_content().replace("/usr/bin/true", "/usr/bin/false")
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=drifted)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.READY


def test_invalid_collects_multiple_issues_at_once() -> None:
    pr = ScriptedProcessRunner()  # no systemctl
    env = ScriptedEnv.darwin(home=HOME)  # not linux
    assessment = make_changer(
        pr=pr,
        env=env,
        unit_content="garbage",
        unit_name="weird.thing",
    ).assess_state()

    assert assessment.state is ExistingState.INVALID
    joined = " ".join(assessment.issues)
    assert "Linux-only" in joined
    assert "systemctl not on PATH" in joined
    assert "unit suffix unrecognised" in joined
    assert "no [Section] header" in joined


def test_invalid_when_unit_name_contains_slash() -> None:
    assessment = make_changer(unit_name="dir/foo.service").assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("path separators" in i for i in assessment.issues)


def test_baseline_is_ready() -> None:
    # Sanity check that the helper's defaults aren't accidentally INVALID.
    assert make_changer().assess_state().state is ExistingState.READY


def test_system_scope_uses_etc_systemd_system() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/systemd"))
    fs.add_dir(Path("/etc/systemd/system"))
    assessment = make_changer(fs=fs, scope="system").assess_state()
    assert assessment.state is ExistingState.READY
