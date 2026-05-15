from __future__ import annotations

import os
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, Sequence

from dependency_injector import containers, providers

from statectl._deferred_handle import DeferredHandle
from statectl._engine_error import (
    DeferredWithoutDependenciesError,
    DuplicateNodeError,
    UnknownDependencyError,
)
from statectl._engine_result import EngineResult, NodeOutcome, NodeReport
from statectl._execution_node import (
    DeferredFactory,
    ExecutionNode,
    PublishCallback,
)
from statectl._interfaces.env import Env
from statectl._interfaces.fs import FileSystem
from statectl._interfaces.http import HttpClient
from statectl._interfaces.logger import Logger
from statectl._interfaces.process import ProcessRunner
from statectl._interfaces.registry import (
    DuplicateVariableError,
    VariableNotFoundError,
    VariableRegistry,
    VariableTypeError,
)
from statectl._modules import (
    DefaultLogger,
    InMemoryVariableRegistry,
    RealEnv,
    RealFileSystem,
    RealHttpClient,
    RealProcessRunner,
)
from statectl._statechangers.state_changers import StateChangers
from statectl._state_changer import (
    ExistingState,
    Result,
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


_PUBLISH_ELIGIBLE: frozenset[NodeOutcome] = frozenset(
    {NodeOutcome.SUCCESS, NodeOutcome.SKIPPED_ALREADY_APPLIED}
)

_ENGINE_FAILURE_OUTCOMES: frozenset[NodeOutcome] = frozenset(
    {NodeOutcome.FAILED_INVALID, NodeOutcome.FAILED_TRANSITION}
)


@dataclass
class _RunState:
    remaining: dict[ExecutionNode, int]
    downstreams: dict[ExecutionNode, list[ExecutionNode]]
    outcomes: dict[ExecutionNode, NodeOutcome] = field(default_factory=dict)
    node_reports: dict[ExecutionNode, NodeReport] = field(default_factory=dict)


class StateCtl:
    def __init__(
        self,
        logger: Logger,
        file_system: FileSystem,
        process_runner: ProcessRunner,
        http_client: HttpClient,
        env: Env,
        variable_registry: VariableRegistry,
    ) -> None:
        self._logger: Logger = logger
        self._fs: FileSystem = file_system
        self._pr: ProcessRunner = process_runner
        self._http: HttpClient = http_client
        self._env: Env = env
        self._registry: VariableRegistry = variable_registry
        self._nodes: list[ExecutionNode] = []
        self._node_by_handle_id: dict[int, ExecutionNode] = {}
        self._deferred_counter: int = 0

    def changers(self) -> StateChangers:
        return StateChangers(
            file_system=self._fs,
            process_runner=self._pr,
            http_client=self._http,
            env=self._env,
        )

    def registry(self) -> VariableRegistry:
        return self._registry

    def add(
        self,
        changer: StateChanger,
        depends_on: Sequence[StateChanger | DeferredHandle] = (),
        publishes: PublishCallback | None = None,
    ) -> None:
        if id(changer) in self._node_by_handle_id:
            raise DuplicateNodeError(changer.name())
        upstreams = self._resolve_upstreams(changer.name(), depends_on)
        node = ExecutionNode(
            changer=changer,
            upstreams=upstreams,
            publishes=publishes,
        )
        self._nodes.append(node)
        self._node_by_handle_id[id(changer)] = node

    def add_deferred(
        self,
        factory: DeferredFactory,
        depends_on: Sequence[StateChanger | DeferredHandle],
        publishes: PublishCallback | None = None,
    ) -> DeferredHandle:
        if not depends_on:
            raise DeferredWithoutDependenciesError()
        self._deferred_counter += 1
        placeholder = f"deferred#{self._deferred_counter}"
        handle = DeferredHandle(placeholder)
        upstreams = self._resolve_upstreams(placeholder, depends_on)
        node = ExecutionNode(
            upstreams=upstreams,
            factory=factory,
            publishes=publishes,
            placeholder_name=placeholder,
        )
        self._nodes.append(node)
        self._node_by_handle_id[id(handle)] = node
        return handle

    def _resolve_upstreams(
        self,
        node_name: str,
        depends_on: Sequence[StateChanger | DeferredHandle],
    ) -> list[ExecutionNode]:
        upstreams: list[ExecutionNode] = []
        for dep in depends_on:
            dep_node = self._node_by_handle_id.get(id(dep))
            if dep_node is None:
                dep_name = (
                    dep.name()
                    if isinstance(dep, StateChanger)
                    else dep.placeholder_name
                )
                raise UnknownDependencyError(node_name, dep_name)
            upstreams.append(dep_node)
        return upstreams

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

        state = _RunState(remaining=dict(in_degree), downstreams=downstreams)
        self._drive_pool(state, workers)

        reports: tuple[NodeReport, ...] = tuple(
            state.node_reports.get(
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

    def _drive_pool(self, state: _RunState, workers: int) -> None:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            in_flight: dict[Future[NodeReport], ExecutionNode] = {}

            def submit(n: ExecutionNode) -> None:
                in_flight[pool.submit(self._run_node, n)] = n

            for n in self._nodes:
                if state.remaining[n] == 0:
                    submit(n)

            while in_flight:
                done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED)
                for fut in done:
                    node = in_flight.pop(fut)
                    self._absorb_completion(node, fut.result(), state, submit)

    def _absorb_completion(
        self,
        node: ExecutionNode,
        report: NodeReport,
        state: _RunState,
        submit: Callable[[ExecutionNode], None],
    ) -> None:
        state.outcomes[node] = report.outcome
        state.node_reports[node] = report

        if report.outcome in _ENGINE_FAILURE_OUTCOMES:
            self._mark_blocked(node, state)
            return

        for d in state.downstreams[node]:
            if d in state.outcomes:
                continue
            state.remaining[d] -= 1
            if state.remaining[d] == 0:
                submit(d)

    def _mark_blocked(self, start_node: ExecutionNode, state: _RunState) -> None:
        queue: deque[ExecutionNode] = deque(state.downstreams[start_node])
        while queue:
            d = queue.popleft()
            if d in state.outcomes:
                continue
            state.outcomes[d] = NodeOutcome.BLOCKED
            state.node_reports[d] = NodeReport(
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
            for nxt in state.downstreams[d]:
                queue.append(nxt)

    def _run_node(self, node: ExecutionNode) -> NodeReport:
        if node.is_deferred:
            resolve_failure = self._resolve_deferred(node)
            if resolve_failure is not None:
                return resolve_failure
        changer = node.changer
        assert changer is not None
        name = node.name()
        assessment = changer.assess_state()
        self._logger.info(
            "[%s] assess: %s (%s)",
            name,
            assessment.state.value,
            assessment.description,
        )

        if assessment.state is ExistingState.ALREADY_APPLIED:
            report = NodeReport(
                node_name=name,
                outcome=NodeOutcome.SKIPPED_ALREADY_APPLIED,
                assessment=assessment,
                result=None,
            )
            return self._maybe_publish(node, changer, report, result=None)

        if assessment.state is ExistingState.INVALID:
            for issue in assessment.issues:
                self._logger.error("[%s] invalid: %s", name, issue)
            return NodeReport(
                node_name=name,
                outcome=NodeOutcome.FAILED_INVALID,
                assessment=assessment,
                result=None,
            )

        return self._finalise_node(node, name, changer, assessment)

    def _resolve_deferred(self, node: ExecutionNode) -> NodeReport | None:
        factory = node.factory
        assert factory is not None
        placeholder = node.name()
        try:
            produced = factory(self._registry)
        except VariableNotFoundError as e:
            return self._deferred_failure_report(
                placeholder, f"MISSING_VAR:{e.name}", str(e)
            )
        except VariableTypeError as e:
            return self._deferred_failure_report(
                placeholder, f"VAR_TYPE:{e.name}", str(e)
            )
        except Exception as e:
            return self._deferred_failure_report(
                placeholder,
                f"DEFERRED_FACTORY_ERROR:{type(e).__name__}",
                f"{type(e).__name__}: {e}",
            )
        if not isinstance(produced, StateChanger):
            return self._deferred_failure_report(
                placeholder,
                "DEFERRED_FACTORY_TYPE",
                (
                    f"deferred factory returned {type(produced).__name__}; "
                    f"expected a StateChanger"
                ),
            )
        node.resolve(produced)
        return None

    @staticmethod
    def _deferred_failure_report(name: str, code: str, message: str) -> NodeReport:
        return NodeReport(
            node_name=name,
            outcome=NodeOutcome.FAILED_INVALID,
            assessment=None,
            result=Result.failure(code=code, message=message),
        )

    def _finalise_node(
        self,
        node: ExecutionNode,
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
                report = NodeReport(
                    node_name=name,
                    outcome=NodeOutcome.SUCCESS,
                    assessment=assessment,
                    result=result,
                    post_assess=post_assess,
                )
                return self._maybe_publish(node, changer, report, result=result)
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

    def _maybe_publish(
        self,
        node: ExecutionNode,
        changer: StateChanger,
        report: NodeReport,
        result: Result | None,
    ) -> NodeReport:
        callback = node.publishes
        if callback is None:
            return report
        if report.outcome not in _PUBLISH_ELIGIBLE:
            return report
        publish_input = result if result is not None else Result.success()
        try:
            produced = callback(changer, publish_input)
        except Exception as e:
            self._logger.error(
                "[%s] publish callback raised: %s", report.node_name, e
            )
            return NodeReport(
                node_name=report.node_name,
                outcome=NodeOutcome.FAILED_TRANSITION,
                assessment=report.assessment,
                result=Result.failure(
                    code=f"PUBLISH_RAISED:{type(e).__name__}",
                    message=f"{type(e).__name__}: {e}",
                ),
                post_assess=report.post_assess,
            )
        try:
            for var_name, value in produced.items():
                self._registry.bind(var_name, value)
        except DuplicateVariableError as e:
            self._logger.error(
                "[%s] publish duplicate variable: %s", report.node_name, e.name
            )
            return NodeReport(
                node_name=report.node_name,
                outcome=NodeOutcome.FAILED_TRANSITION,
                assessment=report.assessment,
                result=Result.failure(
                    code=f"PUBLISH_DUPLICATE:{e.name}",
                    message=str(e),
                ),
                post_assess=report.post_assess,
            )
        return report

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
        http_client: HttpClient | None = None,
        env: Env | None = None,
        variable_registry: VariableRegistry | None = None,
    ) -> StateCtl:
        container = _Container()
        if file_system is not None:
            container.filesystem.override(providers.Object(file_system))
        if process_runner is not None:
            container.process_runner.override(providers.Object(process_runner))
        if http_client is not None:
            container.http_client.override(providers.Object(http_client))
        if env is not None:
            container.env.override(providers.Object(env))
        if variable_registry is not None:
            container.variable_registry.override(providers.Object(variable_registry))
        return container.engine()


class _Container(containers.DeclarativeContainer):
    logger = providers.Singleton(DefaultLogger)
    filesystem = providers.Singleton(RealFileSystem)
    process_runner = providers.Singleton(RealProcessRunner)
    http_client = providers.Singleton(RealHttpClient)
    env = providers.Singleton(RealEnv)
    variable_registry = providers.Singleton(InMemoryVariableRegistry)
    engine = providers.Singleton(
        StateCtl,
        logger=logger,
        file_system=filesystem,
        process_runner=process_runner,
        http_client=http_client,
        env=env,
        variable_registry=variable_registry,
    )
