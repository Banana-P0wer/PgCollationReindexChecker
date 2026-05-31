from __future__ import annotations

from .amcheck import verify_databases_with_failures
from .decision import decide_compare_result
from .models import CompareResult, DatabaseFailure
from .progress import ProgressReporter


def compare_databases(
    options,
    databases: list[str],
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    verify_mode: str = "normal",
    install_extension: bool = False,
    lock_timeout: str = "5s",
    statement_timeout: str = "30min",
    progress: ProgressReporter | None = None,
) -> list[CompareResult]:
    results, failures = compare_databases_with_failures(
        options=options,
        databases=databases,
        provider=provider,
        schema=schema,
        include_system=include_system,
        largest=largest,
        verify_mode=verify_mode,
        install_extension=install_extension,
        lock_timeout=lock_timeout,
        statement_timeout=statement_timeout,
        progress=progress,
        continue_on_error=False,
    )
    if failures:
        raise RuntimeError(failures[0].message)
    return results


def compare_databases_with_failures(
    options,
    databases: list[str],
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    verify_mode: str = "normal",
    install_extension: bool = False,
    lock_timeout: str = "5s",
    statement_timeout: str = "30min",
    progress: ProgressReporter | None = None,
    continue_on_error: bool = False,
) -> tuple[list[CompareResult], list[DatabaseFailure]]:
    progress = progress or ProgressReporter()
    from .scanner import scan_databases_with_failures

    scan_results, scan_failures = scan_databases_with_failures(
        options=options,
        databases=databases,
        provider=provider,
        schema=schema,
        include_system=include_system,
        largest=largest,
        progress=progress,
        continue_on_error=continue_on_error,
    )
    failed_scan_databases = {failure.database_name for failure in scan_failures}
    verify_databases_scope = [
        database for database in databases if database not in failed_scan_databases
    ]
    amcheck_results, verify_failures = verify_databases_with_failures(
        options=options,
        databases=verify_databases_scope,
        mode=verify_mode,
        provider=provider,
        schema=schema,
        include_system=include_system,
        largest=largest,
        install_extension=install_extension,
        lock_timeout=lock_timeout,
        statement_timeout=statement_timeout,
        progress=progress,
        continue_on_error=continue_on_error,
    )
    amcheck_by_index = {
        (result.database_name, result.index_oid): result
        for result in amcheck_results
    }
    combined: list[CompareResult] = []
    for scan in scan_results:
        amcheck = amcheck_by_index.get((scan.database_name, scan.index_oid))
        status = amcheck.status if amcheck else None
        final_decision, reason = decide_compare_result(scan.decision, status)
        combined.append(
            CompareResult(
                scan=scan,
                amcheck=amcheck,
                final_decision=final_decision,
                reason=reason,
            )
        )
    return sort_compare_results(combined), [*scan_failures, *verify_failures]


def sort_compare_results(results: list[CompareResult]) -> list[CompareResult]:
    priority = {
        "REINDEX_REQUIRED_BY_BOTH": 0,
        "REINDEX_REQUIRED_BY_AMCHECK": 1,
        "REINDEX_RECOMMENDED_BY_COLLATION_VERSION": 2,
        "UNKNOWN": 3,
        "OK": 4,
    }
    return sorted(
        results,
        key=lambda result: (
            priority.get(result.final_decision, 99),
            result.scan.database_name,
            result.scan.index_schema,
            result.scan.index_name,
        ),
    )
