from __future__ import annotations

import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from dependency_injector import containers, providers

from statectl.engine_error import (
    CycleDetectedError,
    DuplicateNodeError,
    UnknownDependencyError,
)
from statectl.engine_result import EngineResult, NodeOutcome, NodeReport
from statectl.execution_node import ExecutionNode
from statectl.interfaces.logger import Logger
from statectl.modules.fs.real_file_system import RealFileSystem
from statectl.modules.logger.default_logger import DefaultLogger
from statectl.modules.process.real_process_runner import RealProcessRunner
from statectl.state_changer import (
    ExistingState,
    Result,
    ResultStatus,
    StateAssessment,
)


class StateCtlEngine:
    def __init__(self, logger: Logger) -> None:
        self._logger: Logger = logger
        self._nodes: list[ExecutionNode] = []

    def add(self, node: ExecutionNode) -> None:
        if any(n is node for n in self._nodes):
            raise DuplicateNodeError(node.name())
        self._nodes.append(node)

    def start(self, max_workers: int | None = None) -> EngineResult:
        registered: set[int] = {id(n) for n in self._nodes}
        for node in self._nodes:
            for up in node.upstreams:
                if id(up) not in registered:
                    raise UnknownDependencyError(node.name(), up.name())

        downstreams: dict[ExecutionNode, list[ExecutionNode]] = {
            n: [] for n in self._nodes
        }
        in_degree: dict[ExecutionNode, int] = {n: len(n.upstreams) for n in self._nodes}
        for node in self._nodes:
            for up in node.upstreams:
                downstreams[up].append(node)

        self._detect_cycle(in_degree, downstreams)

        workers: int = max_workers if max_workers is not None else (os.cpu_count() or 1)
        self._logger.info(
            "StateCtlEngine started with %d node(s), max_workers=%d",
            len(self._nodes),
            workers,
        )

        outcomes: dict[ExecutionNode, NodeOutcome] = {}
        assessments: dict[ExecutionNode, StateAssessment] = {}
        results: dict[ExecutionNode, Result] = {}
        remaining: dict[ExecutionNode, int] = dict(in_degree)

        def mark_blocked(start_node: ExecutionNode) -> None:
            queue: deque[ExecutionNode] = deque(downstreams[start_node])
            while queue:
                d = queue.popleft()
                if d in outcomes:
                    continue
                outcomes[d] = NodeOutcome.BLOCKED
                self._logger.warning(
                    "[%s] blocked: upstream %s failed",
                    d.name(),
                    start_node.name(),
                )
                for nxt in downstreams[d]:
                    queue.append(nxt)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            in_flight: dict[Future[NodeReport], ExecutionNode] = {}

            def submit(n: ExecutionNode) -> None:
                fut = pool.submit(self._run_node, n)
                in_flight[fut] = n

            for n in self._nodes:
                if remaining[n] == 0:
                    submit(n)

            while in_flight:
                done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
                for fut in done:
                    node = in_flight.pop(fut)
                    report = fut.result()
                    outcomes[node] = report.outcome
                    if report.assessment is not None:
                        assessments[node] = report.assessment
                    if report.result is not None:
                        results[node] = report.result

                    if report.outcome in {
                        NodeOutcome.FAILED_INVALID,
                        NodeOutcome.FAILED_TRANSITION,
                    }:
                        mark_blocked(node)
                        continue

                    for d in downstreams[node]:
                        if d in outcomes:
                            continue
                        remaining[d] -= 1
                        if remaining[d] == 0:
                            submit(d)

        reports: list[NodeReport] = []
        for n in self._nodes:
            reports.append(
                NodeReport(
                    node_name=n.name(),
                    outcome=outcomes.get(n, NodeOutcome.BLOCKED),
                    assessment=assessments.get(n),
                    result=results.get(n),
                )
            )

        engine_result = EngineResult(reports=tuple(reports))
        self._logger.info(
            "StateCtlEngine finished: ok=%s (%d node(s))",
            engine_result.ok,
            len(reports),
        )
        return engine_result

    def _detect_cycle(
        self,
        in_degree: dict[ExecutionNode, int],
        downstreams: dict[ExecutionNode, list[ExecutionNode]],
    ) -> None:
        remaining: dict[ExecutionNode, int] = dict(in_degree)
        queue: deque[ExecutionNode] = deque(
            n for n in self._nodes if remaining[n] == 0
        )
        visited: int = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for d in downstreams[node]:
                remaining[d] -= 1
                if remaining[d] == 0:
                    queue.append(d)
        if visited < len(self._nodes):
            names = [n.name() for n in self._nodes if remaining[n] > 0]
            raise CycleDetectedError(names)

    def _run_node(self, node: ExecutionNode) -> NodeReport:
        name = node.name()
        changer = node.changer
        assessment = changer.assess_state()
        self._logger.info(
            "[%s] assess: %s (%s)", name, assessment.state.value, assessment.description
        )

        if assessment.state is ExistingState.ALREADY_APPLIED:
            return NodeReport(
                node_name=name,
                outcome=NodeOutcome.SKIPPED_ALREADY_APPLIED,
                assessment=assessment,
                result=None,
            )

        if assessment.state is ExistingState.INVALID:
            for issue in assessment.issues:
                self._logger.error("[%s] invalid: %s", name, issue)
            return NodeReport(
                node_name=name,
                outcome=NodeOutcome.FAILED_INVALID,
                assessment=assessment,
                result=None,
            )

        result = changer.transition()
        if result.status is ResultStatus.SUCCESS:
            self._logger.info(
                "[%s] transition: %s", name, result.message or result.code
            )
            outcome = NodeOutcome.SUCCESS
        elif result.status is ResultStatus.SKIPPED:
            self._logger.info(
                "[%s] transition skipped: %s", name, result.message or result.code
            )
            outcome = NodeOutcome.SKIPPED_BY_TRANSITION
        else:
            self._logger.error(
                "[%s] transition failed: %s %s", name, result.code, result.message
            )
            outcome = NodeOutcome.FAILED_TRANSITION

        return NodeReport(
            node_name=name,
            outcome=outcome,
            assessment=assessment,
            result=result,
        )

    @staticmethod
    def create_engine() -> StateCtlEngine:
        container = _Container()
        return container.engine()


class _Container(containers.DeclarativeContainer):
    logger = providers.Singleton(DefaultLogger)
    filesystem = providers.Singleton(RealFileSystem)
    process_runner = providers.Singleton(RealProcessRunner)
    engine = providers.Singleton(StateCtlEngine, logger=logger)
