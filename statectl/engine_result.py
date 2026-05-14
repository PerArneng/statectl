from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from statectl.state_changer import Result, StateAssessment


class NodeOutcome(Enum):
    SUCCESS = "success"
    SKIPPED_ALREADY_APPLIED = "already_applied"
    SKIPPED_BY_TRANSITION = "skipped"
    FAILED_INVALID = "invalid"
    FAILED_TRANSITION = "failed"
    BLOCKED = "blocked"


_FAILURE_OUTCOMES: frozenset[NodeOutcome] = frozenset(
    {NodeOutcome.FAILED_INVALID, NodeOutcome.FAILED_TRANSITION, NodeOutcome.BLOCKED}
)


@dataclass(frozen=True)
class NodeReport:
    node_name: str
    outcome: NodeOutcome
    assessment: StateAssessment | None
    result: Result | None


@dataclass(frozen=True)
class EngineResult:
    reports: tuple[NodeReport, ...]

    @property
    def ok(self) -> bool:
        return not any(r.outcome in _FAILURE_OUTCOMES for r in self.reports)
