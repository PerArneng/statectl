from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._launchd_helpers import (
    DEFAULT_LABEL,
    HOME,
    USER_AGENTS_DIR,
    make_changer,
    make_env_darwin,
    make_fs_with_user_agents_dir,
    make_plist,
    make_pr_with_launchctl,
)


def test_invalid_when_platform_is_not_darwin() -> None:
    env = ScriptedEnv.linux(home=HOME)
    fs = make_fs_with_user_agents_dir()
    assessment = make_changer(env=env, fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("macOS-only" in i for i in assessment.issues)


def test_invalid_when_launchctl_not_on_path() -> None:
    pr = ScriptedProcessRunner()  # launchctl NOT registered
    assessment = make_changer(pr=pr).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("launchctl not on PATH" in i for i in assessment.issues)


def test_invalid_when_plist_content_not_xml() -> None:
    assessment = make_changer(plist_content="not <valid xml").assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("does not parse as XML" in i for i in assessment.issues)


def test_invalid_when_plist_label_does_not_match_params_label() -> None:
    plist_with_wrong_label = make_plist(label="com.someone.else")
    assessment = make_changer(plist_content=plist_with_wrong_label).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("plist Label mismatch" in i for i in assessment.issues)


def test_invalid_when_plist_has_no_label_key() -> None:
    plist_no_label = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict>'
        "<key>ProgramArguments</key><array/>"
        "</dict></plist>\n"
    )
    assessment = make_changer(plist_content=plist_no_label).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("does not contain a Label key" in i for i in assessment.issues)


def test_invalid_when_plist_dir_does_not_exist() -> None:
    from tests.fakes.in_memory_file_system import InMemoryFileSystem

    fs = InMemoryFileSystem()  # no /Users/test/Library/LaunchAgents
    fs.add_dir(HOME)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("plist directory does not exist" in i for i in assessment.issues)


def test_invalid_when_plist_dir_not_writable() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_dir(USER_AGENTS_DIR, writable=False)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not writable" in i for i in assessment.issues)


def test_invalid_when_existing_plist_has_different_label() -> None:
    fs = make_fs_with_user_agents_dir()
    other_plist = make_plist(label="com.other.agent")
    fs.add_file(USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist", content=other_plist)
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("belongs to a different agent" in i for i in assessment.issues)


def test_invalid_when_plist_path_is_a_directory() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_dir(USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist")
    assessment = make_changer(fs=fs).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in assessment.issues)


def test_invalid_when_loaded_true_and_user_scope_missing_domain_target() -> None:
    assessment = make_changer(domain_target=None).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("requires explicit domain_target" in i for i in assessment.issues)


def test_invalid_collects_multiple_issues_at_once() -> None:
    pr = ScriptedProcessRunner()  # no launchctl
    env = ScriptedEnv.linux(home=HOME)  # not darwin
    fs = make_fs_with_user_agents_dir()
    assessment = make_changer(
        fs=fs,
        pr=pr,
        env=env,
        plist_content="<not><xml/>",
    ).assess_state()

    assert assessment.state is ExistingState.INVALID
    joined = " ".join(assessment.issues)
    assert "macOS-only" in joined
    assert "launchctl not on PATH" in joined
    assert "does not parse as XML" in joined


def test_system_scope_defaults_domain_target_to_system() -> None:
    # scope=system, loaded=True, domain_target=None → effective domain "system",
    # so this is NOT an INVALID for missing domain_target.
    fs = make_fs_with_user_agents_dir()
    # we still need /Library/LaunchDaemons accessible
    fs.add_dir(Path("/Library"))
    fs.add_dir(Path("/Library/LaunchDaemons"))
    assessment = make_changer(
        fs=fs,
        scope="system",
        domain_target=None,
    ).assess_state()

    # plist not present in /Library/LaunchDaemons, dir is writable: READY
    assert assessment.state is ExistingState.READY


def test_pr_with_launchctl_not_used_directly_in_invariant_check() -> None:
    # Sanity: an otherwise-valid changer with no plist on disk should be READY,
    # so the invalid suite is actually catching INVALID cases.
    assessment = make_changer().assess_state()
    assert assessment.state is ExistingState.READY


def test_make_pr_helper_is_usable() -> None:
    assert make_pr_with_launchctl().which("launchctl") is not None
    assert make_env_darwin().platform() == "darwin"
