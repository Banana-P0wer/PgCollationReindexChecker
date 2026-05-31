from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PROVIDER_NAMES = {
    "b": "builtin",
    "c": "libc",
    "d": "database_default",
    "i": "icu",
}

SCAN_OK = "OK"
SCAN_OK_UNVERSIONED = "OK_UNVERSIONED"
SCAN_VERSION_MISMATCH = "VERSION_MISMATCH"
SCAN_UNKNOWN_NO_STORED_VERSION = "UNKNOWN_NO_STORED_VERSION"
SCAN_UNKNOWN_NO_ACTUAL_VERSION = "UNKNOWN_NO_ACTUAL_VERSION"

VERDICT_OK = "OK"
VERDICT_REINDEX_BY_VERSION = "REINDEX_RECOMMENDED_BY_COLLATION_VERSION"
VERDICT_REINDEX_BY_AMCHECK = "REINDEX_REQUIRED_BY_AMCHECK"
VERDICT_REINDEX_BY_BOTH = "REINDEX_REQUIRED_BY_BOTH"
VERDICT_UNKNOWN = "UNKNOWN"

AMCHECK_OK = "AMCHECK_OK"
AMCHECK_FAILED = "AMCHECK_FAILED"
AMCHECK_TIMEOUT = "AMCHECK_TIMEOUT"
AMCHECK_SKIPPED_EXTENSION_MISSING = "SKIPPED_EXTENSION_MISSING"
AMCHECK_SKIPPED_PERMISSION_DENIED = "SKIPPED_PERMISSION_DENIED"
AMCHECK_UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class CollationDependency:
    database_name: str
    key_position: int | None
    key_name: str
    key_type: str
    opclass_name: str | None
    dependency_source: str
    collation_oid: int
    collation_schema: str
    collation_name: str
    collation_provider: str
    effective_provider: str
    stored_version: str | None
    actual_version: str | None
    version_source: str
    status: str
    refresh_sql: str

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAMES.get(self.effective_provider, self.effective_provider)

    @property
    def qualified_collation(self) -> str:
        return f"{self.collation_schema}.{self.collation_name}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provider_name"] = self.provider_name
        data["qualified_collation"] = self.qualified_collation
        return data


@dataclass
class ScanResult:
    database_name: str
    index_oid: int
    index_schema: str
    index_name: str
    table_schema: str
    table_name: str
    access_method: str
    index_size_bytes: int
    is_unique: bool
    is_valid: bool
    is_ready: bool
    index_definition: str
    reindex_sql: str
    decision: str
    dependencies: list[CollationDependency] = field(default_factory=list)

    @property
    def qualified_index(self) -> str:
        return f"{self.index_schema}.{self.index_name}"

    @property
    def qualified_table(self) -> str:
        return f"{self.table_schema}.{self.table_name}"

    @property
    def refresh_sql(self) -> list[str]:
        seen: set[str] = set()
        commands: list[str] = []
        for dependency in self.dependencies:
            if dependency.refresh_sql not in seen:
                seen.add(dependency.refresh_sql)
                commands.append(dependency.refresh_sql)
        return commands

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_name": self.database_name,
            "index_oid": self.index_oid,
            "index_schema": self.index_schema,
            "index_name": self.index_name,
            "qualified_index": self.qualified_index,
            "table_schema": self.table_schema,
            "table_name": self.table_name,
            "qualified_table": self.qualified_table,
            "access_method": self.access_method,
            "index_size_bytes": self.index_size_bytes,
            "is_unique": self.is_unique,
            "is_valid": self.is_valid,
            "is_ready": self.is_ready,
            "index_definition": self.index_definition,
            "reindex_sql": self.reindex_sql,
            "refresh_sql": self.refresh_sql,
            "decision": self.decision,
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
        }


@dataclass
class AmcheckResult:
    database_name: str
    index_oid: int
    index_schema: str
    index_name: str
    table_schema: str
    table_name: str
    index_size_bytes: int
    mode: str
    status: str
    duration_ms: int | None
    reindex_sql: str
    index_definition: str
    error_sqlstate: str | None = None
    error_message: str | None = None

    @property
    def qualified_index(self) -> str:
        return f"{self.index_schema}.{self.index_name}"

    @property
    def qualified_table(self) -> str:
        return f"{self.table_schema}.{self.table_name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_name": self.database_name,
            "index_oid": self.index_oid,
            "index_schema": self.index_schema,
            "index_name": self.index_name,
            "qualified_index": self.qualified_index,
            "table_schema": self.table_schema,
            "table_name": self.table_name,
            "qualified_table": self.qualified_table,
            "index_size_bytes": self.index_size_bytes,
            "mode": self.mode,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_sqlstate": self.error_sqlstate,
            "error_message": self.error_message,
            "reindex_sql": self.reindex_sql,
            "index_definition": self.index_definition,
        }


@dataclass
class CompareResult:
    scan: ScanResult
    amcheck: AmcheckResult | None
    final_decision: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_decision": self.final_decision,
            "reason": self.reason,
            "scan": self.scan.to_dict(),
            "amcheck": self.amcheck.to_dict() if self.amcheck else None,
        }


@dataclass
class DatabaseFailure:
    database_name: str
    command: str
    error_type: str
    message: str
    sqlstate: str | None = None

    @classmethod
    def from_exception(cls, database_name: str, command: str, exc: Exception) -> "DatabaseFailure":
        return cls(
            database_name=database_name,
            command=command,
            error_type=exc.__class__.__name__,
            message=str(exc).strip(),
            sqlstate=getattr(exc, "sqlstate", None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "database_name": self.database_name,
            "command": self.command,
            "error_type": self.error_type,
            "message": self.message,
            "sqlstate": self.sqlstate,
        }
