from __future__ import annotations

from typing import Any

from .db import ConnectionOptions, read_sql


PROVIDER_FILTERS = {
    "all": "all",
    "builtin": "b",
    "libc": "c",
    "icu": "i",
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
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
) -> list[dict[str, Any]]:
    provider_code = PROVIDER_FILTERS[provider]
    params = {
        "include_system": include_system,
        "schema": schema,
        "provider": provider_code,
    }
    with options.connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(read_sql("list_index_collations.sql"), params)
            rows = list(cur.fetchall())
    if largest is not None:
        seen: set[tuple[str, int]] = set()
        limited: list[dict[str, Any]] = []
        for row in rows:
            key = (row["database_name"], row["index_oid"])
            if key not in seen and len(seen) >= largest:
                continue
            seen.add(key)
            limited.append(row)
        return limited
    return rows
