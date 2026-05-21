from __future__ import annotations

from dataclasses import dataclass

from .db import ConnectionOptions
from .errors import UnsupportedPostgresError


MIN_SUPPORTED_SERVER_VERSION_NUM = 150000
MIN_SUPPORTED_SERVER_VERSION_LABEL = "15"


@dataclass(frozen=True)
class ServerInfo:
    version_num: int
    version: str


def load_server_info(options: ConnectionOptions, database: str) -> ServerInfo:
    with options.connect(database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    current_setting('server_version_num')::integer AS version_num,
                    current_setting('server_version') AS version
                """
            )
            row = cur.fetchone()
            return ServerInfo(version_num=row["version_num"], version=row["version"])


def ensure_supported_postgres(options: ConnectionOptions, database: str) -> ServerInfo:
    info = load_server_info(options, database)
    if info.version_num < MIN_SUPPORTED_SERVER_VERSION_NUM:
        raise UnsupportedPostgresError(
            "unsupported PostgreSQL version "
            f"{info.version}; supported PostgreSQL >= {MIN_SUPPORTED_SERVER_VERSION_LABEL}"
        )
    return info
