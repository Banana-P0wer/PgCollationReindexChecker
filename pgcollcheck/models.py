from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import DatabaseOperationError


PROVIDER_NAMES = {
    "b": "builtin",
    "c": "libc",
    "d": "database_default",
    "i": "icu",
}


def quoteIdentifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def quoteQualifiedName(schema: str, name: str) -> str:
    return f"{quoteIdentifier(schema)}.{quoteIdentifier(name)}"

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
    databaseName: str
    keyPosition: int | None
    keyName: str
    keyType: str
    keyExpression: str
    opclassName: str | None
    dependencySource: str
    collationOid: int
    collationSchema: str
    collationName: str
    collationProvider: str
    effectiveProvider: str
    storedVersion: str | None
    actualVersion: str | None
    versionSource: str
    status: str
    refreshSql: str

    @property
    def providerName(self) -> str:
        return PROVIDER_NAMES.get(self.effectiveProvider, self.effectiveProvider)

    @property
    def qualifiedCollation(self) -> str:
        return f"{self.collationSchema}.{self.collationName}"

    @property
    def quotedQualifiedCollation(self) -> str:
        return quoteQualifiedName(self.collationSchema, self.collationName)

    def toDict(self) -> dict[str, Any]:
        return {
            "database_name": self.databaseName,
            "key_position": self.keyPosition,
            "key_name": self.keyName,
            "key_type": self.keyType,
            "key_expression": self.keyExpression,
            "opclass_name": self.opclassName,
            "dependency_source": self.dependencySource,
            "collation_oid": self.collationOid,
            "collation_schema": self.collationSchema,
            "collation_name": self.collationName,
            "collation_provider": self.collationProvider,
            "effective_provider": self.effectiveProvider,
            "stored_version": self.storedVersion,
            "actual_version": self.actualVersion,
            "version_source": self.versionSource,
            "status": self.status,
            "refresh_sql": self.refreshSql,
            "provider_name": self.providerName,
            "qualified_collation": self.qualifiedCollation,
            "quoted_qualified_collation": self.quotedQualifiedCollation,
        }


@dataclass
class ScanResult:
    databaseName: str
    indexOid: int
    indexSchema: str
    indexName: str
    tableSchema: str
    tableName: str
    accessMethod: str
    indexSizeBytes: int
    isUnique: bool
    isValid: bool
    isReady: bool
    indexDefinition: str
    reindexSql: str
    decision: str
    dependencies: list[CollationDependency] = field(default_factory=list)

    @property
    def qualifiedIndex(self) -> str:
        return f"{self.indexSchema}.{self.indexName}"

    @property
    def quotedQualifiedIndex(self) -> str:
        return quoteQualifiedName(self.indexSchema, self.indexName)

    @property
    def qualifiedTable(self) -> str:
        return f"{self.tableSchema}.{self.tableName}"

    @property
    def quotedQualifiedTable(self) -> str:
        return quoteQualifiedName(self.tableSchema, self.tableName)

    @property
    def refreshSql(self) -> list[str]:
        seen: set[str] = set()
        commands: list[str] = []
        for dependency in self.dependencies:
            if dependency.refreshSql not in seen:
                seen.add(dependency.refreshSql)
                commands.append(dependency.refreshSql)
        return commands

    def toDict(self) -> dict[str, Any]:
        return {
            "database_name": self.databaseName,
            "index_oid": self.indexOid,
            "index_schema": self.indexSchema,
            "index_name": self.indexName,
            "qualified_index": self.qualifiedIndex,
            "quoted_qualified_index": self.quotedQualifiedIndex,
            "table_schema": self.tableSchema,
            "table_name": self.tableName,
            "qualified_table": self.qualifiedTable,
            "quoted_qualified_table": self.quotedQualifiedTable,
            "access_method": self.accessMethod,
            "index_size_bytes": self.indexSizeBytes,
            "is_unique": self.isUnique,
            "is_valid": self.isValid,
            "is_ready": self.isReady,
            "index_definition": self.indexDefinition,
            "reindex_sql": self.reindexSql,
            "refresh_sql": self.refreshSql,
            "decision": self.decision,
            "dependencies": [dependency.toDict() for dependency in self.dependencies],
        }


@dataclass
class AmcheckResult:
    databaseName: str
    indexOid: int
    indexSchema: str
    indexName: str
    tableSchema: str
    tableName: str
    indexSizeBytes: int
    mode: str
    status: str
    durationMs: int | None
    reindexSql: str
    indexDefinition: str
    errorSqlstate: str | None = None
    errorMessage: str | None = None

    @property
    def qualifiedIndex(self) -> str:
        return f"{self.indexSchema}.{self.indexName}"

    @property
    def quotedQualifiedIndex(self) -> str:
        return quoteQualifiedName(self.indexSchema, self.indexName)

    @property
    def qualifiedTable(self) -> str:
        return f"{self.tableSchema}.{self.tableName}"

    @property
    def quotedQualifiedTable(self) -> str:
        return quoteQualifiedName(self.tableSchema, self.tableName)

    def toDict(self) -> dict[str, Any]:
        return {
            "database_name": self.databaseName,
            "index_oid": self.indexOid,
            "index_schema": self.indexSchema,
            "index_name": self.indexName,
            "qualified_index": self.qualifiedIndex,
            "quoted_qualified_index": self.quotedQualifiedIndex,
            "table_schema": self.tableSchema,
            "table_name": self.tableName,
            "qualified_table": self.qualifiedTable,
            "quoted_qualified_table": self.quotedQualifiedTable,
            "index_size_bytes": self.indexSizeBytes,
            "mode": self.mode,
            "status": self.status,
            "duration_ms": self.durationMs,
            "error_sqlstate": self.errorSqlstate,
            "error_message": self.errorMessage,
            "reindex_sql": self.reindexSql,
            "index_definition": self.indexDefinition,
        }


@dataclass
class CompareResult:
    scan: ScanResult
    amcheck: AmcheckResult | None
    finalDecision: str
    reason: str

    def toDict(self) -> dict[str, Any]:
        return {
            "final_decision": self.finalDecision,
            "reason": self.reason,
            "scan": self.scan.toDict(),
            "amcheck": self.amcheck.toDict() if self.amcheck else None,
        }


@dataclass
class DatabaseFailure:
    databaseName: str
    command: str
    errorType: str
    message: str
    sqlstate: str | None = None

    @classmethod
    def fromException(cls, databaseName: str, command: str, exc: Exception) -> "DatabaseFailure":
        if isinstance(exc, DatabaseOperationError):
            return cls(
                databaseName=exc.databaseName,
                command=exc.command,
                errorType=exc.errorType,
                message=exc.message,
                sqlstate=exc.sqlstate,
            )
        return cls(
            databaseName=databaseName,
            command=command,
            errorType=exc.__class__.__name__,
            message=str(exc).strip(),
            sqlstate=getattr(exc, "sqlstate", None),
        )

    def toError(self) -> DatabaseOperationError:
        return DatabaseOperationError(
            databaseName=self.databaseName,
            command=self.command,
            errorType=self.errorType,
            message=self.message,
            sqlstate=self.sqlstate,
        )

    def toDict(self) -> dict[str, Any]:
        return {
            "database_name": self.databaseName,
            "command": self.command,
            "error_type": self.errorType,
            "message": self.message,
            "sqlstate": self.sqlstate,
        }
