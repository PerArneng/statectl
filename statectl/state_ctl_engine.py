from __future__ import annotations

from dependency_injector import containers, providers

from statectl.interfaces.logger import Logger
from statectl.modules.fs.real_file_system import RealFileSystem
from statectl.modules.logger.default_logger import DefaultLogger
from statectl.modules.process.real_process_runner import RealProcessRunner
from statectl.state_changer import ExistingState, ResultStatus, StateChanger


class StateCtlEngine:
    def __init__(self, logger: Logger) -> None:
        self._logger = logger
        self._changers: list[StateChanger] = []

    def add(self, changer: StateChanger) -> None:
        self._changers.append(changer)

    def start(self) -> None:
        self._logger.info("StateCtlEngine started with %d changer(s)", len(self._changers))
        for changer in self._changers:
            if not self._run(changer):
                self._logger.error("stopping; remaining changers will not run")
                return
        self._logger.info("StateCtlEngine finished")

    def _run(self, changer: StateChanger) -> bool:
        name = changer.name()
        assessment = changer.assess_state()
        self._logger.info("[%s] assess: %s (%s)", name, assessment.state.value, assessment.description)

        if assessment.state is ExistingState.ALREADY_APPLIED:
            return True

        if assessment.state is ExistingState.INVALID:
            for issue in assessment.issues:
                self._logger.error("[%s] invalid: %s", name, issue)
            return False

        result = changer.transition()
        if result.status is ResultStatus.SUCCESS:
            self._logger.info("[%s] transition: %s", name, result.message or result.code)
            return True
        if result.status is ResultStatus.SKIPPED:
            self._logger.info("[%s] transition skipped: %s", name, result.message or result.code)
            return True
        self._logger.error("[%s] transition failed: %s %s", name, result.code, result.message)
        return False

    @staticmethod
    def create_engine() -> StateCtlEngine:
        container = _Container()
        return container.engine()


class _Container(containers.DeclarativeContainer):
    logger = providers.Singleton(DefaultLogger)
    filesystem = providers.Singleton(RealFileSystem)
    process_runner = providers.Singleton(RealProcessRunner)
    engine = providers.Singleton(StateCtlEngine, logger=logger)
