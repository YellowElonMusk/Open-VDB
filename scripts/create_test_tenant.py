"""Create a test tenant with an admin API key.

Usage:
    # With the full stack running:
    python -m scripts.create_test_tenant

    # Or standalone (generates SQL you can paste into psql):
    python scripts/create_test_tenant.py --sql-only
"""

import argparse
import asyncio
import hashlib
import secrets
import sys
import uuid
from datetime import datetime, timezone


def generate_api_key(scope: str) -> str:
    prefix = "vdb_adm" if scope == "admin" else "vdb_ret"
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def print_sql(tenant_name: str, tenant_slug: str):
    """Print SQL statements to manually insert a test tenant."""
    tenant_id = uuid.uuid4()
    admin_key = generate_api_key("admin")
    retrieval_key = generate_api_key("retrieval")
    admin_hash = hash_api_key(admin_key)
    retrieval_hash = hash_api_key(retrieval_key)
    now = datetime.now(timezone.utc).isoformat()

    print("-- Run this SQL in your PostgreSQL database:")
    print(f"""
INSERT INTO tenants (id, name, slug, is_active, created_at)
VALUES ('{tenant_id}', '{tenant_name}', '{tenant_slug}', true, '{now}');

INSERT INTO api_keys (id, tenant_id, key_hash, label, scope, is_active, created_at)
VALUES ('{uuid.uuid4()}', '{tenant_id}', '{admin_hash}', 'Test admin key', 'admin', true, '{now}');

INSERT INTO api_keys (id, tenant_id, key_hash, label, scope, is_active, created_at)
VALUES ('{uuid.uuid4()}', '{tenant_id}', '{retrieval_hash}', 'Test retrieval key', 'retrieval', true, '{now}');
""")
    print("=" * 60)
    print(f"Tenant:        {tenant_name} ({tenant_slug})")
    print(f"Admin key:     {admin_key}")
    print(f"Retrieval key: {retrieval_key}")
    print("=" * 60)
    print("\nUse the admin key in the web UI Connect page.")


async def create_via_api(tenant_name: str, tenant_slug: str):
    """Create tenant via the running API."""
    try:
        import httpx
    except ImportError:
        print("httpx not installed. Install it or use --sql-only mode.")
        print("  pip install httpx")
        sys.exit(1)

    base_url = "http://localhost:8000/api/v1"

    async with httpx.AsyncClient() as client:
        # Create tenant
        resp = await client.post(
            f"{base_url}/tenants",
            json={"name": tenant_name, "slug": tenant_slug},
        )
        if resp.status_code == 409:
            print(f"Tenant '{tenant_slug}' already exists.")
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json()
        admin_key = data["admin_api_key"]

        # Create a retrieval key
        resp = await client.post(
            f"{base_url}/tenants/keys",
            headers={"X-API-Key": admin_key},
            json={"label": "Test retrieval key", "scope": "retrieval"},
        )
        resp.raise_for_status()
        retrieval_key = resp.json()["api_key"]

    print("=" * 60)
    print(f"Tenant:        {data['name']} ({data['slug']})")
    print(f"Admin key:     {admin_key}")
    print(f"Retrieval key: {retrieval_key}")
    print("=" * 60)
    print("\nUse the admin key in the web UI Connect page.")


def main():
    parser = argparse.ArgumentParser(description="Create a test tenant")
    parser.add_argument("--name", default="Test OEM", help="Tenant name")
    parser.add_argument("--slug", default="test-oem", help="Tenant slug")
    parser.add_argument("--sql-only", action="store_true", help="Print SQL instead of calling API")
    args = parser.parse_args()

    if args.sql_only:
        print_sql(args.name, args.slug)
    else:
        asyncio.run(create_via_api(args.name, args.slug))


if __name__ == "__main__":
    main()
