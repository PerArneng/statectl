from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override

from statectl._interfaces.env import Env
from statectl._interfaces.fs import FileSystem
from statectl._interfaces.process import ProcessRunner
from statectl._modules import RealEnv, RealFileSystem, RealProcessRunner
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)
from statectl._statechangers.ensure_launchd_agent import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentStateChanger,
)
from statectl._statechangers.ensure_systemd_unit import (
    EnsureSystemdUnitParameters,
    EnsureSystemdUnitStateChanger,
)


_UNSUPPORTED_LABEL: str = "__statectl_unsupported__"
_UNSUPPORTED_UNIT_NAME: str = "__statectl_unsupported__.service"


@dataclass(frozen=True)
class LaunchdSpec:
    label: str
    plist_content: str
    scope: Literal["user", "system"]
    domain_target: str | None = None

    @classmethod
    def unsupported(cls) -> LaunchdSpec:
        return cls(
            label=_UNSUPPORTED_LABEL,
            plist_content="",
            scope="user",
            domain_target=None,
        )

    def is_unsupported(self) -> bool:
        return self.label == _UNSUPPORTED_LABEL and self.plist_content == ""


@dataclass(frozen=True)
class SystemdSpec:
    unit_name: str
    unit_content: str
    scope: Literal["system", "user"]

    @classmethod
    def unsupported(cls) -> SystemdSpec:
        return cls(
            unit_name=_UNSUPPORTED_UNIT_NAME,
            unit_content="",
            scope="system",
        )

    def is_unsupported(self) -> bool:
        return (
            self.unit_name == _UNSUPPORTED_UNIT_NAME and self.unit_content == ""
        )


@dataclass(frozen=True)
class EnsureServiceParameters(Parameters):
    darwin: LaunchdSpec
    linux: SystemdSpec
    enabled: bool = True
    started: bool = True


def _build_darwin_changer(
    params: EnsureServiceParameters,
    file_system: FileSystem,
    process_runner: ProcessRunner,
    env: Env,
) -> EnsureLaunchdAgentStateChanger:
    spec = params.darwin
    return EnsureLaunchdAgentStateChanger(
        EnsureLaunchdAgentParameters(
            label=spec.label,
            plist_content=spec.plist_content,
            scope=spec.scope,
            loaded=params.started,
            domain_target=spec.domain_target,
        ),
        file_system=file_system,
        process_runner=process_runner,
        env=env,
    )


def _build_linux_changer(
    params: EnsureServiceParameters,
    file_system: FileSystem,
    process_runner: ProcessRunner,
    env: Env,
) -> EnsureSystemdUnitStateChanger:
    spec = params.linux
    return EnsureSystemdUnitStateChanger(
        EnsureSystemdUnitParameters(
            unit_name=spec.unit_name,
            unit_content=spec.unit_content,
            scope=spec.scope,
            enabled=params.enabled,
            started=params.started,
        ),
        file_system=file_system,
        process_runner=process_runner,
        env=env,
    )


class EnsureServiceStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureServiceParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()
        self._cached_delegate: StateChanger | None = None
        self._delegate_built: bool = False

    @property
    def params(self) -> EnsureServiceParameters:
        return self._params

    @override
    def name(self) -> str:
        platform = self._env.platform()
        if platform == "darwin":
            return f"ensure-service:{self._params.darwin.label}"
        if platform == "linux":
            return f"ensure-service:{self._params.linux.unit_name}"
        return "ensure-service:unsupported-platform"

    def _platform_issue(self) -> str | None:
        platform = self._env.platform()
        if platform == "darwin":
            if self._params.darwin.is_unsupported():
                return "no darwin spec provided"
            return None
        if platform == "linux":
            if self._params.linux.is_unsupported():
                return "no linux spec provided"
            return None
        return f"unsupported platform: {platform!r}"

    def _delegate(self) -> StateChanger | None:
        if self._delegate_built:
            return self._cached_delegate
        platform = self._env.platform()
        if platform == "darwin":
            self._cached_delegate = _build_darwin_changer(
                self._params, self._fs, self._pr, self._env
            )
        elif platform == "linux":
            self._cached_delegate = _build_linux_changer(
                self._params, self._fs, self._pr, self._env
            )
        else:
            self._cached_delegate = None
        self._delegate_built = True
        return self._cached_delegate

    @override
    def assess_state(self) -> StateAssessment:
        issue = self._platform_issue()
        if issue is not None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure service",
                issues=[issue],
            )
        delegate = self._delegate()
        if delegate is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot ensure service",
                issues=["no delegate available for current platform"],
            )
        return delegate.assess_state()

    @override
    def transition(self) -> Result:
        delegate = self._delegate()
        if delegate is None:
            return Result.failure(
                "UNSUPPORTED_PLATFORM",
                f"no delegate for platform {self._env.platform()!r}",
            )
        return delegate.transition()

    @override
    def rollback(self) -> StateChanger:
        return EnsureServiceRollbackStateChanger(
            self._params,
            file_system=self._fs,
            process_runner=self._pr,
            env=self._env,
        )


def _build_darwin_rollback(
    params: EnsureServiceParameters,
    file_system: FileSystem,
    process_runner: ProcessRunner,
    env: Env,
) -> StateChanger:
    return _build_darwin_changer(params, file_system, process_runner, env).rollback()


def _build_linux_rollback(
    params: EnsureServiceParameters,
    file_system: FileSystem,
    process_runner: ProcessRunner,
    env: Env,
) -> StateChanger:
    return _build_linux_changer(params, file_system, process_runner, env).rollback()


class EnsureServiceRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureServiceParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
        env: Env | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()
        self._env: Env = env or RealEnv()
        self._cached_delegate: StateChanger | None = None
        self._delegate_built: bool = False

    @property
    def params(self) -> EnsureServiceParameters:
        return self._params

    @override
    def name(self) -> str:
        platform = self._env.platform()
        if platform == "darwin":
            return f"ensure-service-rollback:{self._params.darwin.label}"
        if platform == "linux":
            return f"ensure-service-rollback:{self._params.linux.unit_name}"
        return "ensure-service-rollback:unsupported-platform"

    def _platform_issue(self) -> str | None:
        platform = self._env.platform()
        if platform == "darwin":
            if self._params.darwin.is_unsupported():
                return "no darwin spec provided"
            return None
        if platform == "linux":
            if self._params.linux.is_unsupported():
                return "no linux spec provided"
            return None
        return f"unsupported platform: {platform!r}"

    def _delegate(self) -> StateChanger | None:
        if self._delegate_built:
            return self._cached_delegate
        platform = self._env.platform()
        if platform == "darwin":
            self._cached_delegate = _build_darwin_rollback(
                self._params, self._fs, self._pr, self._env
            )
        elif platform == "linux":
            self._cached_delegate = _build_linux_rollback(
                self._params, self._fs, self._pr, self._env
            )
        else:
            self._cached_delegate = None
        self._delegate_built = True
        return self._cached_delegate

    @override
    def assess_state(self) -> StateAssessment:
        issue = self._platform_issue()
        if issue is not None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back service",
                issues=[issue],
            )
        delegate = self._delegate()
        if delegate is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description="cannot roll back service",
                issues=["no delegate available for current platform"],
            )
        return delegate.assess_state()

    @override
    def transition(self) -> Result:
        delegate = self._delegate()
        if delegate is None:
            return Result.failure(
                "UNSUPPORTED_PLATFORM",
                f"no delegate for platform {self._env.platform()!r}",
            )
        return delegate.transition()
