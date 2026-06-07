from __future__ import annotations

from typing import Any

from .db import ConnectionOptions, readSql


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


def listDatabases(options: ConnectionOptions, maintenanceDb: str) -> list[str]:
    with options.connect(maintenanceDb) as conn:
        with conn.cursor() as cur:
            cur.execute(readSql("list_databases.sql"))
            return [row["datname"] for row in cur.fetchall()]


def listIndexCollationRows(
    options: ConnectionOptions,
    database: str,
    provider: str = "all",
    accessMethod: str = "btree",
    schema: str | None = None,
    includeSystem: bool = False,
) -> list[dict[str, Any]]:
    providerCode = PROVIDER_FILTERS[provider]
    accessMethodName = ACCESS_METHOD_FILTERS[accessMethod]
    params = {
        "include_system": includeSystem,
        "schema": schema,
        "provider": providerCode,
        "access_method": accessMethodName,
    }
    with options.connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(readSql("list_index_collations.sql"), params)
            return list(cur.fetchall())
