from __future__ import annotations

from typing import Any

from .decision import classify_collation_version, decide_scan_result
from .discovery import list_index_collation_rows
from .models import CollationDependency, DatabaseFailure, ScanResult
from .progress import ProgressReporter


def scan_database(
    options,
    database: str,
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
) -> list[ScanResult]:
    rows = list_index_collation_rows(
        options=options,
        database=database,
        provider=provider,
        schema=schema,
        include_system=include_system,
    )
    return limit_scan_results(build_scan_results(rows), largest)


def scan_databases(
    options,
    databases: list[str],
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    progress: ProgressReporter | None = None,
) -> list[ScanResult]:
    results, failures = scan_databases_with_failures(
        options=options,
        databases=databases,
        provider=provider,
        schema=schema,
        include_system=include_system,
        largest=largest,
        progress=progress,
        continue_on_error=False,
    )
    if failures:
        raise RuntimeError(failures[0].message)
    return results


def scan_databases_with_failures(
    options,
    databases: list[str],
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    progress: ProgressReporter | None = None,
    continue_on_error: bool = False,
) -> tuple[list[ScanResult], list[DatabaseFailure]]:
    progress = progress or ProgressReporter()
    results: list[ScanResult] = []
    failures: list[DatabaseFailure] = []
    for database in databases:
        progress.database("scanning", database)
        try:
            results.extend(
                scan_database(
                    options=options,
                    database=database,
                    provider=provider,
                    schema=schema,
                    include_system=include_system,
                    largest=largest,
                )
            )
        except Exception as exc:
            if not continue_on_error:
                raise
            failures.append(DatabaseFailure.from_exception(database, "scan", exc))
            progress.write(f"failed scanning database {database}: {exc}")
    return sort_scan_results(results), failures


def build_scan_results(rows: list[dict[str, Any]]) -> list[ScanResult]:
    grouped: dict[tuple[str, int], ScanResult] = {}
    statuses: dict[tuple[str, int], list[str]] = {}

    for row in rows:
        key = (row["database_name"], row["index_oid"])
        status = classify_collation_version(row["stored_version"], row["actual_version"])
        dependency = CollationDependency(
            database_name=row["database_name"],
            key_position=row["key_position"],
            key_name=row["key_name"],
            key_type=row["key_type"],
            opclass_name=row["opclass_name"],
            dependency_source=row["dependency_source"],
            collation_oid=row["collation_oid"],
            collation_schema=row["collation_schema"],
            collation_name=row["collation_name"],
            collation_provider=row["collation_provider"],
            effective_provider=row["effective_provider"],
            stored_version=row["stored_version"],
            actual_version=row["actual_version"],
            version_source=row["version_source"],
            status=status,
            refresh_sql=row["refresh_sql"],
        )

        if key not in grouped:
            grouped[key] = ScanResult(
                database_name=row["database_name"],
                index_oid=row["index_oid"],
                index_schema=row["index_schema"],
                index_name=row["index_name"],
                table_schema=row["table_schema"],
                table_name=row["table_name"],
                access_method=row["access_method"],
                index_size_bytes=row["index_size_bytes"],
                is_unique=row["is_unique"],
                is_valid=row["is_valid"],
                is_ready=row["is_ready"],
                index_definition=row["index_definition"],
                reindex_sql=row["reindex_sql"],
                decision="",
            )
            statuses[key] = []

        grouped[key].dependencies.append(dependency)
        statuses[key].append(status)

    for key, result in grouped.items():
        result.decision = decide_scan_result(statuses[key])

    return sort_scan_results(list(grouped.values()))


def sort_scan_results(results: list[ScanResult]) -> list[ScanResult]:
    priority = {
        "REINDEX_RECOMMENDED_BY_COLLATION_VERSION": 0,
        "UNKNOWN": 1,
        "OK": 2,
    }
    return sorted(
        results,
        key=lambda result: (
            priority.get(result.decision, 99),
            result.database_name,
            result.index_schema,
            result.index_name,
        ),
    )


def limit_scan_results(results: list[ScanResult], largest: int | None) -> list[ScanResult]:
    if largest is None:
        return sort_scan_results(results)

    kept: dict[tuple[str, int], ScanResult] = {
        (result.database_name, result.index_oid): result
        for result in results
        if result.decision != "OK"
    }
    per_database_counts: dict[str, int] = {}
    by_size = sorted(
        results,
        key=lambda result: (
            result.database_name,
            -result.index_size_bytes,
            result.index_schema,
            result.index_name,
        ),
    )
    for result in by_size:
        if result.decision != "OK":
            continue
        count = per_database_counts.get(result.database_name, 0)
        if count >= largest:
            continue
        kept[(result.database_name, result.index_oid)] = result
        per_database_counts[result.database_name] = count + 1

    return sort_scan_results(list(kept.values()))
