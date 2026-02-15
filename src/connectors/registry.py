"""Connector registry — discover and instantiate connectors by type."""

from src.connectors.base import BaseConnector

_REGISTRY: dict[str, type[BaseConnector]] = {}


def register_connector(cls: type[BaseConnector]) -> type[BaseConnector]:
    """Class decorator to register a connector."""
    _REGISTRY[cls.connector_type.fget(None)] = cls  # type: ignore
    return cls


def get_connector(connector_type: str) -> BaseConnector:
    cls = _REGISTRY.get(connector_type)
    if cls is None:
        available = ", ".join(sorted(_REGISTRY.keys())) or "(none)"
        raise ValueError(f"Unknown connector type '{connector_type}'. Available: {available}")
    return cls()


def list_connectors() -> list[str]:
    return sorted(_REGISTRY.keys())
