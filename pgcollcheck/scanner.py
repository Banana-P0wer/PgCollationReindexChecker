from __future__ import annotations

from typing import Any

from .decision import classifyCollationVersion, decideScanResult
from .discovery import listIndexCollationRows
from .models import CollationDependency, DatabaseFailure, ScanResult
from .progress import ProgressReporter


def scanDatabase(
    options,
    database: str,
    provider: str = "all",
    accessMethod: str = "btree",
    schema: str | None = None,
    includeSystem: bool = False,
    largest: int | None = None,
) -> list[ScanResult]:
    rows = listIndexCollationRows(
        options=options,
        database=database,
        provider=provider,
        accessMethod=accessMethod,
        schema=schema,
        includeSystem=includeSystem,
    )
    return limitScanResults(buildScanResults(rows), largest)


def scanDatabasesWithFailures(
    options,
    databases: list[str],
    provider: str = "all",
    accessMethod: str = "btree",
    schema: str | None = None,
    includeSystem: bool = False,
    largest: int | None = None,
    progress: ProgressReporter | None = None,
    continueOnError: bool = False,
) -> tuple[list[ScanResult], list[DatabaseFailure]]:
    progress = progress or ProgressReporter()
    results: list[ScanResult] = []
    failures: list[DatabaseFailure] = []
    for database in databases:
        progress.database("scanning", database)
        try:
            results.extend(
                scanDatabase(
                    options=options,
                    database=database,
                    provider=provider,
                    accessMethod=accessMethod,
                    schema=schema,
                    includeSystem=includeSystem,
                    largest=largest,
                )
            )
        except Exception as exc:
            failure = DatabaseFailure.fromException(database, "scan", exc)
            if not continueOnError:
                raise failure.toError() from exc
            failures.append(failure)
            progress.write(f"failed scanning database {database}: {exc}")
    return sortScanResults(results), failures


def buildScanResults(rows: list[dict[str, Any]]) -> list[ScanResult]:
    grouped: dict[tuple[str, int], ScanResult] = {}
    statuses: dict[tuple[str, int], list[str]] = {}

    for row in rows:
        key = (row["database_name"], row["index_oid"])
        status = classifyCollationVersion(row["stored_version"], row["actual_version"])
        dependency = CollationDependency(
            databaseName=row["database_name"],
            keyPosition=row["key_position"],
            keyName=row["key_name"],
            keyType=row["key_type"],
            keyExpression=row["key_expression"],
            opclassName=row["opclass_name"],
            dependencySource=row["dependency_source"],
            collationOid=row["collation_oid"],
            collationSchema=row["collation_schema"],
            collationName=row["collation_name"],
            collationProvider=row["collation_provider"],
            effectiveProvider=row["effective_provider"],
            storedVersion=row["stored_version"],
            actualVersion=row["actual_version"],
            versionSource=row["version_source"],
            status=status,
            refreshSql=row["refresh_sql"],
        )

        if key not in grouped:
            grouped[key] = ScanResult(
                databaseName=row["database_name"],
                indexOid=row["index_oid"],
                indexSchema=row["index_schema"],
                indexName=row["index_name"],
                tableSchema=row["table_schema"],
                tableName=row["table_name"],
                accessMethod=row["access_method"],
                indexSizeBytes=row["index_size_bytes"],
                isUnique=row["is_unique"],
                isValid=row["is_valid"],
                isReady=row["is_ready"],
                indexDefinition=row["index_definition"],
                reindexSql=row["reindex_sql"],
                decision="",
            )
            statuses[key] = []

        grouped[key].dependencies.append(dependency)
        statuses[key].append(status)

    for key, result in grouped.items():
        result.decision = decideScanResult(statuses[key])

    return sortScanResults(list(grouped.values()))


def sortScanResults(results: list[ScanResult]) -> list[ScanResult]:
    priority = {
        "REINDEX_RECOMMENDED_BY_COLLATION_VERSION": 0,
        "UNKNOWN": 1,
        "OK": 2,
    }
    return sorted(
        results,
        key=lambda result: (
            priority.get(result.decision, 99),
            result.databaseName,
            result.indexSchema,
            result.indexName,
        ),
    )


def limitScanResults(results: list[ScanResult], largest: int | None) -> list[ScanResult]:
    if largest is None:
        return sortScanResults(results)

    kept: dict[tuple[str, int], ScanResult] = {
        (result.databaseName, result.indexOid): result
        for result in results
        if result.decision != "OK"
    }
    perDatabaseCounts: dict[str, int] = {}
    bySize = sorted(
        results,
        key=lambda result: (
            result.databaseName,
            -result.indexSizeBytes,
            result.indexSchema,
            result.indexName,
        ),
    )
    for result in bySize:
        if result.decision != "OK":
            continue
        count = perDatabaseCounts.get(result.databaseName, 0)
        if count >= largest:
            continue
        kept[(result.databaseName, result.indexOid)] = result
        perDatabaseCounts[result.databaseName] = count + 1

    return sortScanResults(list(kept.values()))
