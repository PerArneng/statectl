from __future__ import annotations


class EngineConfigurationError(Exception):
    """Base for configuration errors raised before any changer runs."""


class UnknownDependencyError(EngineConfigurationError):
    def __init__(self, node: str, missing: str) -> None:
        self.node: str = node
        self.missing: str = missing
        super().__init__(
            f"node {node!r} depends on {missing!r} which was not added to the engine"
        )


class DuplicateNodeError(EngineConfigurationError):
    def __init__(self, name: str) -> None:
        self.node_name: str = name
        super().__init__(f"node {name!r} was added to the engine more than once")


class DeferredWithoutDependenciesError(EngineConfigurationError):
    """`add_deferred()` was called with an empty `depends_on`. A deferred
    node with no dependencies has no signal for when its factory should run."""

    def __init__(self) -> None:
        super().__init__(
            "add_deferred(...) requires a non-empty depends_on; a deferred "
            "node with no dependencies has no signal for when its factory "
            "should run"
        )
