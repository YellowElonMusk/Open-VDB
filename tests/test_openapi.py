"""The OpenAPI spec must stay compatible with Swagger tooling.

- API key auth is declared as a security scheme (Authorize button in
  Swagger UI, working auth in generated clients)
- File download endpoints are documented as binary, not JSON
- /docs serves vendored Swagger UI assets (works air-gapped)
"""

from src.main import app

# Endpoints that intentionally require no API key
PUBLIC_OPERATIONS = {("post", "/api/v1/tenants")}


def _spec():
    return app.openapi()


def test_api_key_security_scheme_declared():
    scheme = _spec()["components"]["securitySchemes"]["ApiKeyAuth"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-API-Key"


def test_protected_endpoints_reference_the_scheme():
    spec = _spec()
    for path, operations in spec["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, op in operations.items():
            if (method, path) in PUBLIC_OPERATIONS:
                assert "security" not in op, f"{method} {path} should be public"
                continue
            schemes = [name for req in op.get("security", []) for name in req]
            assert "ApiKeyAuth" in schemes, f"{method} {path} lacks ApiKeyAuth security"


def test_export_endpoints_document_binary_downloads():
    spec = _spec()
    cases = {
        "/api/v1/export/sqlite": ["application/vnd.sqlite3"],
        "/api/v1/export/markdown": ["text/markdown; charset=utf-8"],
        "/api/v1/documents/{document_id}/export/{format}": [
            "application/vnd.sqlite3",
            "text/markdown; charset=utf-8",
        ],
    }
    for path, media_types in cases.items():
        content = spec["paths"][path]["get"]["responses"]["200"]["content"]
        for mt in media_types:
            assert content[mt]["schema"] == {"type": "string", "format": "binary"}, (path, mt)
        assert "application/json" not in content, path


def test_docs_page_uses_vendored_assets():
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        html = client.get("/docs").text
        assert "/swagger/swagger-ui-bundle.js" in html
        assert "/swagger/swagger-ui.css" in html
        assert "cdn.jsdelivr.net" not in html

        for asset in ("/swagger/swagger-ui-bundle.js", "/swagger/swagger-ui.css"):
            assert client.get(asset).status_code == 200, asset

        assert client.get("/openapi.json").status_code == 200
