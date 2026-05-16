from __future__ import annotations

import pytest

from statectl._state_changer import (
    ExistingState,
    ResultStatus,
    RollbackableStateChanger,
    StateChanger,
)
from statectl._statechangers import (
    EnsureServiceParameters,
    EnsureServiceRollbackStateChanger,
    EnsureServiceStateChanger,
    LaunchdSpec,
    SystemdSpec,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._launchd_helpers import (
    DEFAULT_DOMAIN,
    DEFAULT_LABEL,
    HOME as DARWIN_HOME,
    make_fs_with_user_agents_dir,
    make_plist,
    make_pr_with_launchctl,
)
from statectl._interfaces.process import ProcessResult
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT as DEFAULT_UNIT_NAME,
    HOME as LINUX_HOME,
    SYSTEM_UNIT_DIR,
    make_fs_with_system_unit_dir,
    make_pr_with_systemctl as _make_pr_with_systemctl_bare,
    make_unit_content as make_unit,
)


def make_pr_with_systemctl(
    *, is_active: str = "active", is_enabled: str = "enabled"
) -> ScriptedProcessRunner:
    """Local wrapper that scripts is-active / is-enabled, since main's helper
    only registers the `systemctl` executable. EnsureService tests need the
    delegate to see specific is-active/is-enabled states."""
    pr = _make_pr_with_systemctl_bare()
    for prefix in (("systemctl", "is-enabled"), ("systemctl", "--user", "is-enabled")):
        pr.register(
            prefix,
            ProcessResult(
                exit_code=0 if is_enabled == "enabled" else 1,
                stdout=is_enabled,
                stderr="",
                duration_ms=0,
            ),
        )
    for prefix in (("systemctl", "is-active"), ("systemctl", "--user", "is-active")):
        pr.register(
            prefix,
            ProcessResult(
                exit_code=0 if is_active == "active" else 3,
                stdout=is_active,
                stderr="",
                duration_ms=0,
            ),
        )
    return pr


def _darwin_spec() -> LaunchdSpec:
    return LaunchdSpec(
        label=DEFAULT_LABEL,
        plist_content=make_plist(),
        scope="user",
        domain_target=DEFAULT_DOMAIN,
    )


def _linux_spec() -> SystemdSpec:
    return SystemdSpec(
        unit_name=DEFAULT_UNIT_NAME,
        unit_content=make_unit(),
        scope="system",
    )


def _make_changer(
    *,
    env: ScriptedEnv,
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    darwin: LaunchdSpec | None = None,
    linux: SystemdSpec | None = None,
    enabled: bool = True,
    started: bool = True,
) -> EnsureServiceStateChanger:
    return EnsureServiceStateChanger(
        EnsureServiceParameters(
            darwin=darwin or _darwin_spec(),
            linux=linux or _linux_spec(),
            enabled=enabled,
            started=started,
        ),
        file_system=fs,
        process_runner=pr,
        env=env,
    )


def test_is_a_rollbackable_state_changer() -> None:
    fs = make_fs_with_user_agents_dir()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
    )
    assert isinstance(changer, RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    fs = make_fs_with_user_agents_dir()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
    )
    rb = changer.rollback()
    assert isinstance(rb, StateChanger)
    assert not isinstance(rb, RollbackableStateChanger)
    assert isinstance(rb, EnsureServiceRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = EnsureServiceParameters(darwin=_darwin_spec(), linux=_linux_spec())
    with pytest.raises(Exception):
        params.enabled = False  # type: ignore[misc]


# --- dispatch: darwin ---


def test_dispatch_darwin_assess_ready() -> None:
    fs = make_fs_with_user_agents_dir()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
    )
    assessment = changer.assess_state()
    assert assessment.state is ExistingState.READY


def test_dispatch_darwin_transition_writes_plist() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=pr,
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    plist_path = DARWIN_HOME / "Library/LaunchAgents" / f"{DEFAULT_LABEL}.plist"
    assert fs.read_text_file(plist_path) == make_plist()


def test_dispatch_darwin_name_uses_label() -> None:
    fs = make_fs_with_user_agents_dir()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
    )
    assert changer.name() == f"ensure-service:{DEFAULT_LABEL}"


# --- dispatch: linux ---


def test_dispatch_linux_assess_ready() -> None:
    fs = make_fs_with_system_unit_dir()
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=make_pr_with_systemctl(),
    )
    assert changer.assess_state().state is ExistingState.READY


def test_dispatch_linux_transition_writes_unit_file() -> None:
    fs = make_fs_with_system_unit_dir()
    pr = make_pr_with_systemctl()
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=pr,
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    assert fs.read_text_file(SYSTEM_UNIT_DIR / DEFAULT_UNIT_NAME) == make_unit()


def test_dispatch_linux_name_uses_unit_name() -> None:
    fs = make_fs_with_system_unit_dir()
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=make_pr_with_systemctl(),
    )
    assert changer.name() == f"ensure-service:{DEFAULT_UNIT_NAME}"


# --- pass-through: enabled/started propagate to delegate ---


def test_started_false_propagates_to_linux_delegate() -> None:
    fs = make_fs_with_system_unit_dir()
    pr = make_pr_with_systemctl(is_active="inactive")
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=pr,
        started=False,
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert ("systemctl", "stop", DEFAULT_UNIT_NAME) in argvs


def test_started_propagates_to_darwin_delegate_via_loaded() -> None:
    # With started=False, the launchd delegate gets loaded=False, so it only
    # writes the plist (no launchctl bootstrap). Test by asserting no
    # launchctl bootstrap call was issued.
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=pr,
        started=False,
    )
    result = changer.transition()
    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert not any(a[:2] == ("launchctl", "bootstrap") for a in argvs)


# --- unsupported sentinels and platform mismatches ---


def test_invalid_when_darwin_spec_unsupported_on_darwin() -> None:
    fs = make_fs_with_user_agents_dir()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
        darwin=LaunchdSpec.unsupported(),
    )
    assessment = changer.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("no darwin spec provided" in i for i in assessment.issues)


def test_invalid_when_linux_spec_unsupported_on_linux() -> None:
    fs = make_fs_with_system_unit_dir()
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=make_pr_with_systemctl(),
        linux=SystemdSpec.unsupported(),
    )
    assessment = changer.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("no linux spec provided" in i for i in assessment.issues)


def test_darwin_assess_does_not_require_linux_dir() -> None:
    """A darwin run with `linux=SystemdSpec.unsupported()` should still
    succeed — we only need the platform-relevant spec."""
    fs = make_fs_with_user_agents_dir()
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
        linux=SystemdSpec.unsupported(),
    )
    assert changer.assess_state().state is ExistingState.READY


# --- rollback dispatch ---


def test_rollback_dispatch_darwin_assess_ready_when_plist_present() -> None:
    fs = make_fs_with_user_agents_dir()
    plist_path = DARWIN_HOME / "Library/LaunchAgents" / f"{DEFAULT_LABEL}.plist"
    fs.add_file(plist_path, content=make_plist())
    changer = _make_changer(
        env=ScriptedEnv.darwin(home=DARWIN_HOME),
        fs=fs,
        pr=make_pr_with_launchctl(),
    )
    rb = changer.rollback()
    assert rb.assess_state().state is ExistingState.READY


def test_rollback_dispatch_linux_assess_ready_when_unit_present() -> None:
    fs = make_fs_with_system_unit_dir()
    fs.add_file(SYSTEM_UNIT_DIR / DEFAULT_UNIT_NAME, content=make_unit())
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=make_pr_with_systemctl(),
    )
    rb = changer.rollback()
    assert rb.assess_state().state is ExistingState.READY


def test_rollback_dispatch_linux_transition_unlinks_unit() -> None:
    fs = make_fs_with_system_unit_dir()
    fs.add_file(SYSTEM_UNIT_DIR / DEFAULT_UNIT_NAME, content=make_unit())
    pr = make_pr_with_systemctl()
    changer = _make_changer(
        env=ScriptedEnv.linux(home=LINUX_HOME),
        fs=fs,
        pr=pr,
    )
    result = changer.rollback().transition()
    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(SYSTEM_UNIT_DIR / DEFAULT_UNIT_NAME)


# --- unsupported sentinel helpers ---


def test_launchd_spec_unsupported_helper() -> None:
    spec = LaunchdSpec.unsupported()
    assert spec.is_unsupported()
    # A normal spec should not look unsupported.
    assert not _darwin_spec().is_unsupported()


def test_systemd_spec_unsupported_helper() -> None:
    spec = SystemdSpec.unsupported()
    assert spec.is_unsupported()
    assert not _linux_spec().is_unsupported()


def test_invalid_on_unsupported_platform() -> None:
    # Synthetic env with platform set to something other than darwin/linux.
    fs = make_fs_with_system_unit_dir()
    pr = make_pr_with_systemctl()
    env = ScriptedEnv.linux(home=LINUX_HOME)
    env._platform = "windows"  # type: ignore[assignment]
    changer = _make_changer(env=env, fs=fs, pr=pr)
    assessment = changer.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("unsupported platform" in i for i in assessment.issues)
