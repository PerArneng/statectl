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
