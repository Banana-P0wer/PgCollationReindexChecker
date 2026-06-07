from __future__ import annotations

from .amcheck import verifyDatabasesWithFailures
from .decision import decideCompareResult
from .models import CompareResult, DatabaseFailure
from .progress import ProgressReporter


def compareDatabasesWithFailures(
    options,
    databases: list[str],
    provider: str = "all",
    schema: str | None = None,
    includeSystem: bool = False,
    largest: int | None = None,
    verifyMode: str = "normal",
    installExtension: bool = False,
    lockTimeout: str = "5s",
    statementTimeout: str = "30min",
    progress: ProgressReporter | None = None,
    continueOnError: bool = False,
) -> tuple[list[CompareResult], list[DatabaseFailure]]:
    progress = progress or ProgressReporter()
    from .scanner import scanDatabasesWithFailures

    scanResults, scanFailures = scanDatabasesWithFailures(
        options=options,
        databases=databases,
        provider=provider,
        schema=schema,
        includeSystem=includeSystem,
        largest=largest,
        progress=progress,
        continueOnError=continueOnError,
    )
    failedScanDatabases = {failure.databaseName for failure in scanFailures}
    verifyDatabasesScope = [
        database for database in databases if database not in failedScanDatabases
    ]
    amcheckResults, verifyFailures = verifyDatabasesWithFailures(
        options=options,
        databases=verifyDatabasesScope,
        mode=verifyMode,
        provider=provider,
        schema=schema,
        includeSystem=includeSystem,
        largest=largest,
        installExtension=installExtension,
        lockTimeout=lockTimeout,
        statementTimeout=statementTimeout,
        progress=progress,
        continueOnError=continueOnError,
    )
    amcheckByIndex = {
        (result.databaseName, result.indexOid): result
        for result in amcheckResults
    }
    combined: list[CompareResult] = []
    for scan in scanResults:
        amcheck = amcheckByIndex.get((scan.databaseName, scan.indexOid))
        status = amcheck.status if amcheck else None
        finalDecision, reason = decideCompareResult(scan.decision, status)
        combined.append(
            CompareResult(
                scan=scan,
                amcheck=amcheck,
                finalDecision=finalDecision,
                reason=reason,
            )
        )
    return sortCompareResults(combined), [*scanFailures, *verifyFailures]


def sortCompareResults(results: list[CompareResult]) -> list[CompareResult]:
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
            priority.get(result.finalDecision, 99),
            result.scan.databaseName,
            result.scan.indexSchema,
            result.scan.indexName,
        ),
    )
