"""Example CRM connector — demonstrates the connector pattern.

Replace this with real connectors for Salesforce, HubSpot, etc.
"""

from src.connectors.base import BaseConnector, ConnectorRecord
from src.connectors.registry import register_connector


@register_connector
class ExampleCRMConnector(BaseConnector):
    """A mock CRM connector for development and testing."""

    @property
    def connector_type(self) -> str:
        return "example_crm"

    async def authenticate(self, credentials: dict) -> None:
        token = credentials.get("api_token")
        if not token:
            raise ValueError("Missing 'api_token' in credentials")
        # In a real connector, validate the token against the CRM API.
        self._token = token

    async def fetch_records(self, config: dict | None = None) -> list[ConnectorRecord]:
        # In a real connector, paginate through the CRM API.
        return [
            ConnectorRecord(
                source_id="contact-001",
                content="John Doe — VP Engineering at Acme Corp. Interested in AI-powered support tools.",
                metadata={"type": "contact", "company": "Acme Corp"},
            ),
            ConnectorRecord(
                source_id="contact-002",
                content="Jane Smith — Head of CX at Globex. Evaluating chatbot solutions for Q1.",
                metadata={"type": "contact", "company": "Globex"},
            ),
        ]
