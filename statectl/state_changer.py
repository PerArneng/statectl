from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Parameters:
    """Base for state-changer parameter objects. Subclass and add fields."""


class ExistingState(Enum):
    READY = "ready"
    ALREADY_APPLIED = "already_applied"
    INVALID = "invalid"


@dataclass(frozen=True)
class StateAssessment:
    state: ExistingState
    description: str = ""
    issues: list[str] = field(default_factory=list)

    @property
    def can_transition(self) -> bool:
        return self.state is ExistingState.READY


class ResultStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Result:
    status: ResultStatus
    code: str = ""
    message: str = ""
    details: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is ResultStatus.SUCCESS

    @staticmethod
    def success(message: str = "", code: str = "OK") -> Result:
        return Result(status=ResultStatus.SUCCESS, code=code, message=message)

    @staticmethod
    def failure(code: str, message: str = "") -> Result:
        return Result(status=ResultStatus.FAILURE, code=code, message=message)

    @staticmethod
    def skipped(message: str = "", code: str = "SKIPPED") -> Result:
        return Result(status=ResultStatus.SKIPPED, code=code, message=message)


class StateChanger(ABC):
    """A single, directional state change. Drivers call `assess_state` to
    decide what to do, then `transition` if state is OK. Implementations
    carry their own `Parameters` instance."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def assess_state(self) -> StateAssessment: ...

    @abstractmethod
    def transition(self) -> Result: ...


class RollbackableStateChanger(StateChanger):
    """A `StateChanger` that can produce an inverse `StateChanger` to undo
    its transition. The inverse is itself a plain `StateChanger` (no
    rollback-of-rollback)."""

    @abstractmethod
    def rollback(self) -> StateChanger: ...
