from __future__ import annotations

import argparse
import os
import sys

from .db import ConnectionOptions
from .discovery import list_databases
from .errors import PgCollCheckError
from .exit_codes import ERROR, OK, PARTIAL_FAILURE, REINDEX_RECOMMENDED, UNKNOWN
from .models import (
    AMCHECK_FAILED,
    VERDICT_REINDEX_BY_AMCHECK,
    VERDICT_REINDEX_BY_BOTH,
    VERDICT_REINDEX_BY_VERSION,
)
from .progress import ProgressReporter
from .reports import write_compare_report, write_reindex_plan, write_scan_report, write_verify_report
from .scanner import scan_databases_with_failures
from .server import ensure_supported_postgres


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    options = ConnectionOptions(
        dsn=args.dsn,
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
    )

    try:
        if args.command:
            ensure_supported_postgres(options, version_check_database(args))
        if args.command == "scan":
            return run_scan(args, options)
        if args.command == "verify":
            return run_verify(args, options)
        if args.command == "compare":
            return run_compare(args, options)
        if args.command == "plan-reindex":
            return run_plan_reindex(args, options)
    except PgCollCheckError as exc:
        print(f"pgcollcheck: {exc}", file=sys.stderr)
        return ERROR
    except Exception as exc:
        print(f"pgcollcheck: {exc}", file=sys.stderr)
        return ERROR

    parser.print_help()
    return ERROR


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgcollcheck",
        description="Check PostgreSQL collation versions used by string indexes.",
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", parents=[connection_parent()], help="compare stored and actual collation versions")
    add_scan_args(scan, include_access_method=True)

    verify = subparsers.add_parser("verify", parents=[connection_parent()], help="run amcheck for B-tree indexes with collatable keys")
    add_verify_args(verify)

    compare = subparsers.add_parser("compare", parents=[connection_parent()], help="combine catalog scan and amcheck verification")
    add_compare_args(compare)

    plan = subparsers.add_parser("plan-reindex", parents=[connection_parent()], help="generate SQL commands for indexes that need REINDEX")
    add_scan_args(plan, include_access_method=True)
    plan.add_argument("--sql-output", help="Write generated SQL to this file.")

    return parser


def connection_parent() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="PostgreSQL DSN.")
    parser.add_argument("--host", help="Database host.")
    parser.add_argument("--port", type=int, help="Database port.")
    parser.add_argument("--user", help="Database user.")
    parser.add_argument("--password", help="Database password.")
    parser.add_argument(
        "--maintenance-db",
        default=os.environ.get("PGDATABASE") or "postgres",
        help="Database used to discover all databases. Default: postgres.",
    )
    parser.add_argument("--progress", action="store_true", help="Print progress messages to stderr.")
    return parser


def add_scan_args(parser: argparse.ArgumentParser, include_access_method: bool = False) -> None:
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--database", help="Scan one database. Defaults to --maintenance-db.")
    target.add_argument("--all-databases", action="store_true", help="Scan every non-template database.")
    parser.add_argument("--schema", help="Limit scan to one schema.")
    parser.add_argument(
        "--provider",
        choices=("all", "libc", "icu", "builtin"),
        default="all",
        help="Limit by effective collation provider.",
    )
    if include_access_method:
        parser.add_argument(
            "--access-method",
            choices=("btree", "all"),
            default="btree",
            help="Limit catalog scan by index access method. Default: btree.",
        )
    parser.add_argument("--include-system", action="store_true", help="Include pg_catalog and other system schemas.")
    parser.add_argument(
        "--largest",
        type=positive_int,
        help="Show N largest safe indexes per database, while always keeping REINDEX and UNKNOWN results.",
    )
    parser.add_argument("--only-mismatches", action="store_true", help="Only show indexes that need REINDEX or have UNKNOWN status.")
    parser.add_argument("--format", choices=("table", "json"), default="table", help="Report format.")
    parser.add_argument("--output", help="Write report to this file.")
    parser.add_argument("--strict-exit-code", action="store_true", help="Return code 2 when REINDEX is recommended.")


def add_verify_args(parser: argparse.ArgumentParser) -> None:
    add_scan_args(parser)
    parser.add_argument(
        "--mode",
        choices=("quick", "normal", "deep"),
        default="normal",
        help="amcheck mode. quick skips heapallindexed, deep uses bt_index_parent_check.",
    )
    parser.add_argument("--install-extension", action="store_true", help="Create amcheck if it is missing.")
    parser.add_argument("--lock-timeout", default="5s", help="PostgreSQL lock_timeout for amcheck.")
    parser.add_argument("--statement-timeout", default="30min", help="PostgreSQL statement_timeout for amcheck.")


def add_compare_args(parser: argparse.ArgumentParser) -> None:
    add_scan_args(parser)
    parser.add_argument(
        "--verify-mode",
        choices=("quick", "normal", "deep"),
        default="normal",
        help="amcheck mode used by compare.",
    )
    parser.add_argument("--install-extension", action="store_true", help="Create amcheck if it is missing.")
    parser.add_argument("--lock-timeout", default="5s", help="PostgreSQL lock_timeout for amcheck.")
    parser.add_argument("--statement-timeout", default="30min", help="PostgreSQL statement_timeout for amcheck.")


def run_scan(args: argparse.Namespace, options: ConnectionOptions) -> int:
    databases = resolve_databases(args, options)
    results, failures = scan_databases_with_failures(
        options=options,
        databases=databases,
        provider=args.provider,
        access_method=args.access_method,
        schema=args.schema,
        include_system=args.include_system,
        largest=args.largest,
        progress=ProgressReporter(args.progress),
        continue_on_error=args.all_databases,
    )
    results = filter_scan_results(results, args.only_mismatches)
    write_scan_report(
        results,
        args.format,
        args.output,
        only_mismatches=args.only_mismatches,
        failures=failures,
        scope=report_scope(args, databases),
    )
    return command_exit_code(args.strict_exit_code, [result.decision for result in results], failures)


def run_verify(args: argparse.Namespace, options: ConnectionOptions) -> int:
    from .amcheck import verify_databases_with_failures

    databases = resolve_databases(args, options)
    results, failures = verify_databases_with_failures(
        options=options,
        databases=databases,
        mode=args.mode,
        provider=args.provider,
        schema=args.schema,
        include_system=args.include_system,
        largest=args.largest,
        install_extension=args.install_extension,
        lock_timeout=args.lock_timeout,
        statement_timeout=args.statement_timeout,
        progress=ProgressReporter(args.progress),
        continue_on_error=args.all_databases,
    )
    results = filter_amcheck_results(results, args.only_mismatches)
    write_verify_report(
        results,
        args.format,
        args.output,
        only_mismatches=args.only_mismatches,
        failures=failures,
        scope=report_scope(args, databases),
    )
    if failures:
        return PARTIAL_FAILURE
    if args.strict_exit_code and any(result.status == AMCHECK_FAILED for result in results):
        return REINDEX_RECOMMENDED
    if args.strict_exit_code and any(result.status != "AMCHECK_OK" for result in results):
        return UNKNOWN
    return OK


def run_compare(args: argparse.Namespace, options: ConnectionOptions) -> int:
    from .compare import compare_databases_with_failures

    databases = resolve_databases(args, options)
    results, failures = compare_databases_with_failures(
        options=options,
        databases=databases,
        provider=args.provider,
        schema=args.schema,
        include_system=args.include_system,
        largest=args.largest,
        verify_mode=args.verify_mode,
        install_extension=args.install_extension,
        lock_timeout=args.lock_timeout,
        statement_timeout=args.statement_timeout,
        progress=ProgressReporter(args.progress),
        continue_on_error=args.all_databases,
    )
    results = filter_compare_results(results, args.only_mismatches)
    write_compare_report(
        results,
        args.format,
        args.output,
        only_mismatches=args.only_mismatches,
        failures=failures,
        scope=report_scope(args, databases),
    )
    if failures:
        return PARTIAL_FAILURE
    if args.strict_exit_code and any(
        result.final_decision in (VERDICT_REINDEX_BY_BOTH, VERDICT_REINDEX_BY_AMCHECK, VERDICT_REINDEX_BY_VERSION)
        for result in results
    ):
        return REINDEX_RECOMMENDED
    return scan_exit_code(args.strict_exit_code, [result.final_decision for result in results])


def run_plan_reindex(args: argparse.Namespace, options: ConnectionOptions) -> int:
    databases = resolve_databases(args, options)
    results, failures = scan_databases_with_failures(
        options=options,
        databases=databases,
        provider=args.provider,
        schema=args.schema,
        include_system=args.include_system,
        largest=args.largest,
        progress=ProgressReporter(args.progress),
        continue_on_error=args.all_databases,
    )
    results = filter_scan_results(results, args.only_mismatches)
    if args.output:
        write_scan_report(
            results,
            args.format,
            args.output,
            only_mismatches=args.only_mismatches,
            failures=failures,
            scope=report_scope(args, databases),
        )
    write_reindex_plan(results, args.sql_output, include_database_switches=args.all_databases)
    return command_exit_code(args.strict_exit_code, [result.decision for result in results], failures)


def resolve_databases(args: argparse.Namespace, options: ConnectionOptions) -> list[str]:
    if args.all_databases:
        return list_databases(options, args.maintenance_db)
    return [args.database or args.maintenance_db]


def version_check_database(args: argparse.Namespace) -> str:
    if getattr(args, "all_databases", False):
        return args.maintenance_db
    return getattr(args, "database", None) or args.maintenance_db


def scan_exit_code(strict: bool, decisions: list[str]) -> int:
    if not strict:
        return OK
    if any("REINDEX" in decision for decision in decisions):
        return REINDEX_RECOMMENDED
    if any(decision == "UNKNOWN" for decision in decisions):
        return UNKNOWN
    return OK


def command_exit_code(strict: bool, decisions: list[str], failures: list | None = None) -> int:
    if failures:
        return PARTIAL_FAILURE
    return scan_exit_code(strict, decisions)


def report_scope(args: argparse.Namespace, databases: list[str]) -> dict[str, object]:
    scope: dict[str, object] = {
        "databases": databases,
        "schema": getattr(args, "schema", None),
        "provider": getattr(args, "provider", None),
        "include_system": getattr(args, "include_system", False),
        "largest": getattr(args, "largest", None),
        "only_mismatches": getattr(args, "only_mismatches", False),
        "all_databases": getattr(args, "all_databases", False),
    }
    for name in ("access_method", "mode", "verify_mode"):
        if hasattr(args, name):
            scope[name] = getattr(args, name)
    return scope


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def filter_scan_results(results, only_mismatches: bool):
    if not only_mismatches:
        return results
    return [
        result
        for result in results
        if "REINDEX" in result.decision or result.decision == "UNKNOWN"
    ]


def filter_amcheck_results(results, only_mismatches: bool):
    if not only_mismatches:
        return results
    return [
        result
        for result in results
        if result.status != "AMCHECK_OK"
    ]


def filter_compare_results(results, only_mismatches: bool):
    if not only_mismatches:
        return results
    return [
        result
        for result in results
        if result.final_decision != "OK"
    ]
