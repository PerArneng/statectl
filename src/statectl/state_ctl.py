from __future__ import annotations

import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Sequence

from dependency_injector import containers, providers

from statectl._engine_error import (
    DuplicateNodeError,
    UnknownDependencyError,
)
from statectl._engine_result import EngineResult, NodeOutcome, NodeReport
from statectl._execution_node import ExecutionNode
from statectl._interfaces.fs import FileSystem
from statectl._interfaces.logger import Logger
from statectl._interfaces.process import ProcessRunner
from statectl._modules import DefaultLogger, RealFileSystem, RealProcessRunner
from statectl._statechangers.state_changers import StateChangers
from statectl._state_changer import (
    ExistingState,
    Result,
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


class StateCtl:
    def __init__(
        self,
        logger: Logger,
        file_system: FileSystem,
        process_runner: ProcessRunner,
    ) -> None:
        self._logger: Logger = logger
        self._fs: FileSystem = file_system
        self._pr: ProcessRunner = process_runner
        self._nodes: list[ExecutionNode] = []
        self._node_by_changer_id: dict[int, ExecutionNode] = {}

    def changers(self) -> StateChangers:
        return StateChangers(file_system=self._fs, process_runner=self._pr)

    def add(
        self,
        changer: StateChanger,
        depends_on: Sequence[StateChanger] = (),
    ) -> None:
        if id(changer) in self._node_by_changer_id:
            raise DuplicateNodeError(changer.name())
        upstreams: list[ExecutionNode] = []
        for dep in depends_on:
            dep_node = self._node_by_changer_id.get(id(dep))
            if dep_node is None:
                raise UnknownDependencyError(changer.name(), dep.name())
            upstreams.append(dep_node)
        node = ExecutionNode(changer, upstreams=upstreams)
        self._nodes.append(node)
        self._node_by_changer_id[id(changer)] = node

    def start(self, max_workers: int | None = None) -> EngineResult:
        downstreams: dict[ExecutionNode, list[ExecutionNode]] = {
            n: [] for n in self._nodes
        }
        in_degree: dict[ExecutionNode, int] = {n: len(n.upstreams) for n in self._nodes}
        for node in self._nodes:
            for up in node.upstreams:
                downstreams[up].append(node)

        workers: int = max_workers if max_workers is not None else (os.cpu_count() or 1)
        self._logger.info(
            "StateCtl started with %d node(s), max_workers=%d",
            len(self._nodes),
            workers,
        )

        outcomes: dict[ExecutionNode, NodeOutcome] = {}
        node_reports: dict[ExecutionNode, NodeReport] = {}
        remaining: dict[ExecutionNode, int] = dict(in_degree)

        def mark_blocked(start_node: ExecutionNode) -> None:
            queue: deque[ExecutionNode] = deque(downstreams[start_node])
            while queue:
                d = queue.popleft()
                if d in outcomes:
                    continue
                outcomes[d] = NodeOutcome.BLOCKED
                node_reports[d] = NodeReport(
                    node_name=d.name(),
                    outcome=NodeOutcome.BLOCKED,
                    assessment=None,
                    result=None,
                )
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
                    node_reports[node] = report

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

        reports: tuple[NodeReport, ...] = tuple(
            node_reports.get(
                n,
                NodeReport(
                    node_name=n.name(),
                    outcome=NodeOutcome.BLOCKED,
                    assessment=None,
                    result=None,
                ),
            )
            for n in self._nodes
        )

        engine_result = EngineResult(reports=reports)
        self._logger.info(
            "StateCtl finished: ok=%s (%d node(s))",
            engine_result.ok,
            len(reports),
        )
        return engine_result

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

        return self._finalise_node(name, changer, assessment)

    def _finalise_node(
        self,
        name: str,
        changer: StateChanger,
        assessment: StateAssessment,
    ) -> NodeReport:
        result: Result = changer.transition()
        post_assess: StateAssessment | None = None

        if result.status is ResultStatus.SKIPPED:
            self._logger.info(
                "[%s] transition skipped: %s", name, result.message or result.code
            )
            return NodeReport(
                node_name=name,
                outcome=NodeOutcome.SKIPPED_BY_TRANSITION,
                assessment=assessment,
                result=result,
            )

        if result.status is ResultStatus.SUCCESS:
            self._logger.info(
                "[%s] transition: %s", name, result.message or result.code
            )
            post_assess = changer.assess_state()
            self._logger.info(
                "[%s] post-assess: %s (%s)",
                name,
                post_assess.state.value,
                post_assess.description,
            )
            if post_assess.state is ExistingState.ALREADY_APPLIED:
                return NodeReport(
                    node_name=name,
                    outcome=NodeOutcome.SUCCESS,
                    assessment=assessment,
                    result=result,
                    post_assess=post_assess,
                )
            self._logger.error(
                "[%s] post-assess mismatch: expected ALREADY_APPLIED, got %s",
                name,
                post_assess.state.value,
            )
            result = Result.failure(
                code="POST_ASSESS_MISMATCH",
                message=(
                    f"transition reported SUCCESS but post-assess returned "
                    f"{post_assess.state.value}: {post_assess.description}"
                ),
            )
            outcome: NodeOutcome = NodeOutcome.FAILED_TRANSITION
        else:
            self._logger.error(
                "[%s] transition failed: %s %s", name, result.code, result.message
            )
            outcome = NodeOutcome.FAILED_TRANSITION

        rollback_result: Result | None = self._maybe_rollback(name, changer)
        return NodeReport(
            node_name=name,
            outcome=outcome,
            assessment=assessment,
            result=result,
            post_assess=post_assess,
            rollback_result=rollback_result,
        )

    def _maybe_rollback(
        self,
        name: str,
        changer: StateChanger,
    ) -> Result | None:
        if not isinstance(changer, RollbackableStateChanger):
            return None
        self._logger.info("[%s] rollback: starting", name)
        inverse: StateChanger = changer.rollback()
        rb_result: Result = inverse.transition()
        if rb_result.status is ResultStatus.SUCCESS:
            self._logger.info(
                "[%s] rollback: %s", name, rb_result.message or rb_result.code
            )
        else:
            self._logger.error(
                "[%s] rollback failed: %s %s",
                name,
                rb_result.code,
                rb_result.message,
            )
        return rb_result

    @staticmethod
    def new(
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> StateCtl:
        container = _Container()
        if file_system is not None:
            container.filesystem.override(providers.Object(file_system))
        if process_runner is not None:
            container.process_runner.override(providers.Object(process_runner))
        return container.engine()


class _Container(containers.DeclarativeContainer):
    logger = providers.Singleton(DefaultLogger)
    filesystem = providers.Singleton(RealFileSystem)
    process_runner = providers.Singleton(RealProcessRunner)
    engine = providers.Singleton(
        StateCtl,
        logger=logger,
        file_system=filesystem,
        process_runner=process_runner,
    )
