from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from psycopg import sql

from .discovery import list_index_collation_rows
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
from .scanner import build_scan_results, limit_scan_results


LOCK_OR_TIMEOUT_SQLSTATES = {"55P03", "57014"}
PERMISSION_DENIED_SQLSTATES = {"42501"}


@dataclass(frozen=True)
class AmcheckFunction:
    schema_name: str
    function_name: str
    argument_count: int


def verify_databases(
    options,
    databases: list[str],
    mode: str = "normal",
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    install_extension: bool = False,
    lock_timeout: str = "5s",
    statement_timeout: str = "30min",
    progress: ProgressReporter | None = None,
) -> list[AmcheckResult]:
    results, failures = verify_databases_with_failures(
        options=options,
        databases=databases,
        mode=mode,
        provider=provider,
        schema=schema,
        include_system=include_system,
        largest=largest,
        install_extension=install_extension,
        lock_timeout=lock_timeout,
        statement_timeout=statement_timeout,
        progress=progress,
        continue_on_error=False,
    )
    if failures:
        raise RuntimeError(failures[0].message)
    return results


def verify_databases_with_failures(
    options,
    databases: list[str],
    mode: str = "normal",
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    install_extension: bool = False,
    lock_timeout: str = "5s",
    statement_timeout: str = "30min",
    progress: ProgressReporter | None = None,
    continue_on_error: bool = False,
) -> tuple[list[AmcheckResult], list[DatabaseFailure]]:
    progress = progress or ProgressReporter()
    results: list[AmcheckResult] = []
    failures: list[DatabaseFailure] = []
    for database in databases:
        progress.database("verifying", database)
        try:
            results.extend(
                verify_database(
                    options=options,
                    database=database,
                    mode=mode,
                    provider=provider,
                    schema=schema,
                    include_system=include_system,
                    largest=largest,
                    install_extension=install_extension,
                    lock_timeout=lock_timeout,
                    statement_timeout=statement_timeout,
                )
            )
        except Exception as exc:
            failure = DatabaseFailure.from_exception(database, "verify", exc)
            if not continue_on_error:
                raise failure.to_error() from exc
            failures.append(failure)
            progress.write(f"failed verifying database {database}: {exc}")
    return sort_amcheck_results(results), failures


def verify_database(
    options,
    database: str,
    mode: str = "normal",
    provider: str = "all",
    schema: str | None = None,
    include_system: bool = False,
    largest: int | None = None,
    install_extension: bool = False,
    lock_timeout: str = "5s",
    statement_timeout: str = "30min",
) -> list[AmcheckResult]:
    rows = list_index_collation_rows(
        options=options,
        database=database,
        provider=provider,
        schema=schema,
        include_system=include_system,
    )
    candidates = limit_scan_results(build_scan_results(rows), largest)
    if not candidates:
        return []

    with options.connect(database, autocommit=True) as conn:
        if not has_amcheck(conn):
            if install_extension:
                install_amcheck(conn)
            else:
                return [skipped_extension_result(candidate, mode) for candidate in candidates]

        functions = load_amcheck_functions(conn)
        configure_timeouts(conn, lock_timeout, statement_timeout)
        return [
            run_amcheck_for_index(conn, candidate, mode, functions)
            for candidate in candidates
        ]


def has_amcheck(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'amcheck') AS exists")
        return bool(cur.fetchone()["exists"])


def install_amcheck(conn) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS amcheck")
    except Exception:
        # CREATE EXTENSION IF NOT EXISTS can still race with another session.
        # If the extension appeared meanwhile, the desired state is achieved.
        if has_amcheck(conn):
            return
        raise


def load_amcheck_functions(conn) -> dict[str, AmcheckFunction]:
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
                    schema_name=row["nspname"],
                    function_name=name,
                    argument_count=row["pronargs"],
                )
    return functions


def configure_timeouts(conn, lock_timeout: str, statement_timeout: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lock_timeout', %s, false)", (lock_timeout,))
        cur.execute("SELECT set_config('statement_timeout', %s, false)", (statement_timeout,))


def run_amcheck_for_index(conn, candidate, mode: str, functions: dict[str, AmcheckFunction]) -> AmcheckResult:
    started = time.perf_counter()
    try:
        with conn.cursor() as cur:
            cur.execute(build_amcheck_call(mode, functions), build_amcheck_params(candidate.index_oid, mode, functions))
            cur.fetchone()
        status = AMCHECK_OK
        sqlstate = None
        message = None
    except Exception as exc:
        status = classify_amcheck_error(exc)
        sqlstate = getattr(exc, "sqlstate", None)
        message = str(exc).strip()

    duration_ms = int((time.perf_counter() - started) * 1000)
    return AmcheckResult(
        database_name=candidate.database_name,
        index_oid=candidate.index_oid,
        index_schema=candidate.index_schema,
        index_name=candidate.index_name,
        table_schema=candidate.table_schema,
        table_name=candidate.table_name,
        index_size_bytes=candidate.index_size_bytes,
        mode=mode,
        status=status,
        duration_ms=duration_ms,
        error_sqlstate=sqlstate,
        error_message=message,
        reindex_sql=candidate.reindex_sql,
        index_definition=candidate.index_definition,
    )


def build_amcheck_call(mode: str, functions: dict[str, AmcheckFunction]) -> sql.Composed:
    function = function_for_mode(mode, functions)
    function_identifier = sql.Identifier(function.schema_name, function.function_name)
    if mode in ("quick", "normal"):
        placeholders = sql.SQL("%s::oid::regclass, %s")
        if function.argument_count >= 3:
            placeholders = sql.SQL("%s::oid::regclass, %s, %s")
    else:
        placeholders = sql.SQL("%s::oid::regclass, %s, %s")
        if function.argument_count >= 4:
            placeholders = sql.SQL("%s::oid::regclass, %s, %s, %s")
    return sql.SQL("SELECT {}({})").format(function_identifier, placeholders)


def build_amcheck_params(index_oid: int, mode: str, functions: dict[str, AmcheckFunction]) -> tuple[Any, ...]:
    function = function_for_mode(mode, functions)
    if mode == "quick":
        params: tuple[Any, ...] = (index_oid, False)
    elif mode == "normal":
        params = (index_oid, True)
    else:
        params = (index_oid, True, True)
    if (mode in ("quick", "normal") and function.argument_count >= 3) or (
        mode == "deep" and function.argument_count >= 4
    ):
        params = (*params, True)
    return params


def function_for_mode(mode: str, functions: dict[str, AmcheckFunction]) -> AmcheckFunction:
    name = "bt_index_parent_check" if mode == "deep" else "bt_index_check"
    if name not in functions:
        raise RuntimeError(f"amcheck function {name} was not found")
    return functions[name]


def classify_amcheck_error(exc: Exception) -> str:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate in LOCK_OR_TIMEOUT_SQLSTATES:
        return AMCHECK_TIMEOUT
    if sqlstate in PERMISSION_DENIED_SQLSTATES:
        return AMCHECK_SKIPPED_PERMISSION_DENIED
    return AMCHECK_FAILED if sqlstate else AMCHECK_UNKNOWN_ERROR


def skipped_extension_result(candidate, mode: str) -> AmcheckResult:
    return AmcheckResult(
        database_name=candidate.database_name,
        index_oid=candidate.index_oid,
        index_schema=candidate.index_schema,
        index_name=candidate.index_name,
        table_schema=candidate.table_schema,
        table_name=candidate.table_name,
        index_size_bytes=candidate.index_size_bytes,
        mode=mode,
        status=AMCHECK_SKIPPED_EXTENSION_MISSING,
        duration_ms=None,
        error_sqlstate=None,
        error_message="amcheck extension is not installed in this database",
        reindex_sql=candidate.reindex_sql,
        index_definition=candidate.index_definition,
    )


def sort_amcheck_results(results: list[AmcheckResult]) -> list[AmcheckResult]:
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
            result.database_name,
            result.index_schema,
            result.index_name,
        ),
    )
