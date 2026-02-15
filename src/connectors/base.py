"""Base connector interface for third-party data sources."""

import abc
from dataclasses import dataclass


@dataclass
class ConnectorRecord:
    """A single record fetched from a connector."""
    source_id: str  # unique ID from the source system
    content: str  # text content to embed
    metadata: dict | None = None


class BaseConnector(abc.ABC):
    """All connectors implement this interface."""

    @abc.abstractmethod
    async def authenticate(self, credentials: dict) -> None:
        """Validate credentials and establish a connection."""
        ...

    @abc.abstractmethod
    async def fetch_records(self, config: dict | None = None) -> list[ConnectorRecord]:
        """Pull records from the external system."""
        ...

    @property
    @abc.abstractmethod
    def connector_type(self) -> str:
        """Unique identifier for this connector type."""
        ...
