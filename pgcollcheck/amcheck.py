from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from psycopg import sql

from .discovery import listIndexCollationRows
from .models import (
    AMCHECK_FAILED,
    AMCHECK_OK,
    AMCHECK_SKIPPED_EXTENSION_MISSING,
    AMCHECK_SKIPPED_PERMISSION_DENIED,
    AMCHECK_TIMEOUT,
    AMCHECK_UNKNOWN_ERROR,
    AmcheckResult,
    DatabaseFailure,
)
from .progress import ProgressReporter
from .scanner import buildScanResults, limitScanResults


LOCK_OR_TIMEOUT_SQLSTATES = {"55P03", "57014"}
PERMISSION_DENIED_SQLSTATES = {"42501"}


@dataclass(frozen=True)
class AmcheckFunction:
    schemaName: str
    functionName: str
    argumentCount: int


def verifyDatabasesWithFailures(
    options,
    databases: list[str],
    mode: str = "normal",
    provider: str = "all",
    schema: str | None = None,
    includeSystem: bool = False,
    largest: int | None = None,
    installExtension: bool = False,
    lockTimeout: str = "5s",
    statementTimeout: str = "30min",
    progress: ProgressReporter | None = None,
    continueOnError: bool = False,
) -> tuple[list[AmcheckResult], list[DatabaseFailure]]:
    progress = progress or ProgressReporter()
    results: list[AmcheckResult] = []
    failures: list[DatabaseFailure] = []
    for database in databases:
        progress.database("verifying", database)
        try:
            results.extend(
                verifyDatabase(
                    options=options,
                    database=database,
                    mode=mode,
                    provider=provider,
                    schema=schema,
                    includeSystem=includeSystem,
                    largest=largest,
                    installExtension=installExtension,
                    lockTimeout=lockTimeout,
                    statementTimeout=statementTimeout,
                )
            )
        except Exception as exc:
            failure = DatabaseFailure.fromException(database, "verify", exc)
            if not continueOnError:
                raise failure.toError() from exc
            failures.append(failure)
            progress.write(f"failed verifying database {database}: {exc}")
    return sortAmcheckResults(results), failures


def verifyDatabase(
    options,
    database: str,
    mode: str = "normal",
    provider: str = "all",
    schema: str | None = None,
    includeSystem: bool = False,
    largest: int | None = None,
    installExtension: bool = False,
    lockTimeout: str = "5s",
    statementTimeout: str = "30min",
) -> list[AmcheckResult]:
    rows = listIndexCollationRows(
        options=options,
        database=database,
        provider=provider,
        schema=schema,
        includeSystem=includeSystem,
    )
    candidates = limitScanResults(buildScanResults(rows), largest)
    if not candidates:
        return []

    with options.connect(database, autoCommit=True) as conn:
        if not hasAmcheck(conn):
            if installExtension:
                installAmcheck(conn)
            else:
                return [skippedExtensionResult(candidate, mode) for candidate in candidates]

        functions = loadAmcheckFunctions(conn)
        configureTimeouts(conn, lockTimeout, statementTimeout)
        return [
            runAmcheckForIndex(conn, candidate, mode, functions)
            for candidate in candidates
        ]


def hasAmcheck(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'amcheck') AS exists")
        return bool(cur.fetchone()["exists"])


def installAmcheck(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS amcheck")
    except Exception:
        # CREATE EXTENSION IF NOT EXISTS can still race with another session.
        # If the extension appeared meanwhile, the desired state is achieved.
        if hasAmcheck(conn):
            return
        raise


def loadAmcheckFunctions(conn) -> dict[str, AmcheckFunction]:
    query = """
        SELECT n.nspname, p.proname, p.pronargs
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e'
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE e.extname = 'amcheck'
          AND p.proname IN ('bt_index_check', 'bt_index_parent_check')
        ORDER BY p.proname, p.pronargs DESC
    """
    functions: dict[str, AmcheckFunction] = {}
    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            name = row["proname"]
            if name not in functions:
                functions[name] = AmcheckFunction(
                    schemaName=row["nspname"],
                    functionName=name,
                    argumentCount=row["pronargs"],
                )
    return functions


def configureTimeouts(conn, lockTimeout: str, statementTimeout: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lock_timeout', %s, false)", (lockTimeout,))
        cur.execute("SELECT set_config('statement_timeout', %s, false)", (statementTimeout,))


def runAmcheckForIndex(conn, candidate, mode: str, functions: dict[str, AmcheckFunction]) -> AmcheckResult:
    started = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(buildAmcheckCall(mode, functions), buildAmcheckParams(candidate.indexOid, mode, functions))
            cur.fetchone()
        status = AMCHECK_OK
        sqlstate = None
        message = None
    except Exception as exc:
        status = classifyAmcheckError(exc)
        sqlstate = getattr(exc, "sqlstate", None)
        message = str(exc).strip()

    durationMs = int((time.perf_counter() - started) * 1000)
    return AmcheckResult(
        databaseName=candidate.databaseName,
        indexOid=candidate.indexOid,
        indexSchema=candidate.indexSchema,
        indexName=candidate.indexName,
        tableSchema=candidate.tableSchema,
        tableName=candidate.tableName,
        indexSizeBytes=candidate.indexSizeBytes,
        mode=mode,
        status=status,
        durationMs=durationMs,
        errorSqlstate=sqlstate,
        errorMessage=message,
        reindexSql=candidate.reindexSql,
        indexDefinition=candidate.indexDefinition,
    )


def buildAmcheckCall(mode: str, functions: dict[str, AmcheckFunction]) -> sql.Composed:
    function = functionForMode(mode, functions)
    functionIdentifier = sql.Identifier(function.schemaName, function.functionName)
    if mode in ("quick", "normal"):
        placeholders = sql.SQL("%s::oid::regclass, %s")
        if function.argumentCount >= 3:
            placeholders = sql.SQL("%s::oid::regclass, %s, %s")
    else:
        placeholders = sql.SQL("%s::oid::regclass, %s, %s")
        if function.argumentCount >= 4:
            placeholders = sql.SQL("%s::oid::regclass, %s, %s, %s")
    return sql.SQL("SELECT {}({})").format(functionIdentifier, placeholders)


def buildAmcheckParams(indexOid: int, mode: str, functions: dict[str, AmcheckFunction]) -> tuple[Any, ...]:
    function = functionForMode(mode, functions)
    if mode == "quick":
        params: tuple[Any, ...] = (indexOid, False)
    elif mode == "normal":
        params = (indexOid, True)
    else:
        params = (indexOid, True, True)
    if (mode in ("quick", "normal") and function.argumentCount >= 3) or (
        mode == "deep" and function.argumentCount >= 4
    ):
        params = (*params, True)
    return params


def functionForMode(mode: str, functions: dict[str, AmcheckFunction]) -> AmcheckFunction:
    name = "bt_index_parent_check" if mode == "deep" else "bt_index_check"
    if name not in functions:
        raise RuntimeError(f"amcheck function {name} was not found")
    return functions[name]


def classifyAmcheckError(exc: Exception) -> str:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate in LOCK_OR_TIMEOUT_SQLSTATES:
        return AMCHECK_TIMEOUT
    if sqlstate in PERMISSION_DENIED_SQLSTATES:
        return AMCHECK_SKIPPED_PERMISSION_DENIED
    return AMCHECK_FAILED if sqlstate else AMCHECK_UNKNOWN_ERROR


def skippedExtensionResult(candidate, mode: str) -> AmcheckResult:
    return AmcheckResult(
        databaseName=candidate.databaseName,
        indexOid=candidate.indexOid,
        indexSchema=candidate.indexSchema,
        indexName=candidate.indexName,
        tableSchema=candidate.tableSchema,
        tableName=candidate.tableName,
        indexSizeBytes=candidate.indexSizeBytes,
        mode=mode,
        status=AMCHECK_SKIPPED_EXTENSION_MISSING,
        durationMs=None,
        errorSqlstate=None,
        errorMessage="amcheck extension is not installed in this database",
        reindexSql=candidate.reindexSql,
        indexDefinition=candidate.indexDefinition,
    )


def sortAmcheckResults(results: list[AmcheckResult]) -> list[AmcheckResult]:
    priority = {
        AMCHECK_FAILED: 0,
        AMCHECK_TIMEOUT: 1,
        AMCHECK_UNKNOWN_ERROR: 2,
        AMCHECK_SKIPPED_PERMISSION_DENIED: 3,
        AMCHECK_SKIPPED_EXTENSION_MISSING: 4,
        AMCHECK_OK: 5,
    }
    return sorted(
        results,
        key=lambda result: (
            priority.get(result.status, 99),
            result.databaseName,
            result.indexSchema,
            result.indexName,
        ),
    )
