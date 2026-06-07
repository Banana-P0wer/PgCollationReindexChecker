from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.resources import files
from typing import Any


@dataclass(frozen=True)
class ConnectionOptions:
    dsn: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None

    def connect(self, databaseName: str | None = None, autoCommit: bool = False):
        try:
            psycopg = import_module("psycopg")
            dictRow = import_module("psycopg.rows").dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency psycopg. Install with: python3 -m pip install -e ."
            ) from exc

        kwargs: dict[str, Any] = {"row_factory": dictRow, "autocommit": autoCommit}
        if databaseName:
            kwargs["dbname"] = databaseName
        if self.host:
            kwargs["host"] = self.host
        if self.port:
            kwargs["port"] = self.port
        if self.user:
            kwargs["user"] = self.user
        if self.password:
            kwargs["password"] = self.password

        if self.dsn:
            return psycopg.connect(self.dsn, **kwargs)
        return psycopg.connect(**kwargs)


def readSql(name: str) -> str:
    return files("pgcollcheck").joinpath("sql", name).read_text(encoding="utf-8")
