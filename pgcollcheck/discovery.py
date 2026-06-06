from __future__ import annotations

from typing import Any

from .db import ConnectionOptions, read_sql


PROVIDER_FILTERS = {
    "all": "all",
    "builtin": "b",
    "libc": "c",
    "icu": "i",
}

ACCESS_METHOD_FILTERS = {
    "all": "all",
    "btree": "btree",
}


def list_databases(options: ConnectionOptions, maintenance_db: str) -> list[str]:
    with options.connect(maintenance_db) as conn:
        with conn.cursor() as cur:
            cur.execute(read_sql("list_databases.sql"))
            return [row["datname"] for row in cur.fetchall()]


def list_index_collation_rows(
    options: ConnectionOptions,
    database: str,
    provider: str = "all",
    access_method: str = "btree",
    schema: str | None = None,
    include_system: bool = False,
) -> list[dict[str, Any]]:
    provider_code = PROVIDER_FILTERS[provider]
    access_method_name = ACCESS_METHOD_FILTERS[access_method]
    params = {
        "include_system": include_system,
        "schema": schema,
        "provider": provider_code,
        "access_method": access_method_name,
    }
    with options.connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(read_sql("list_index_collations.sql"), params)
            return list(cur.fetchall())
