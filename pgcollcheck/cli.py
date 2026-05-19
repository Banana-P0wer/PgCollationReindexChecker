from __future__ import annotations

import argparse
import os
import sys

from .db import ConnectionOptions
from .discovery import list_databases
from .models import (
    AMCHECK_FAILED,
    VERDICT_REINDEX_BY_AMCHECK,
    VERDICT_REINDEX_BY_BOTH,
    VERDICT_REINDEX_BY_VERSION,
)
from .reports import write_compare_report, write_reindex_plan, write_scan_report, write_verify_report
from .scanner import scan_databases


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
        if args.command == "scan":
            return run_scan(args, options)
        if args.command == "verify":
            return run_verify(args, options)
        if args.command == "compare":
            return run_compare(args, options)
        if args.command == "plan-reindex":
            return run_plan_reindex(args, options)
    except Exception as exc:
        print(f"pgcollcheck: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgcollcheck",
        description="Check PostgreSQL collation versions used by string indexes.",
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", parents=[connection_parent()], help="compare stored and actual collation versions")
    add_scan_args(scan)

    verify = subparsers.add_parser("verify", parents=[connection_parent()], help="run amcheck for B-tree indexes with collatable keys")
    add_verify_args(verify)

    compare = subparsers.add_parser("compare", parents=[connection_parent()], help="combine catalog scan and amcheck verification")
    add_compare_args(compare)

    plan = subparsers.add_parser("plan-reindex", parents=[connection_parent()], help="generate SQL commands for indexes that need REINDEX")
    add_scan_args(plan)
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
    return parser


def add_scan_args(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument("--include-system", action="store_true", help="Include pg_catalog and other system schemas.")
    parser.add_argument("--largest", type=int, help="Only keep N largest matching indexes per database.")
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
    results = scan_databases(
        options=options,
        databases=databases,
        provider=args.provider,
        schema=args.schema,
        include_system=args.include_system,
        largest=args.largest,
    )
    write_scan_report(results, args.format, args.output)
    if args.strict_exit_code and any(result.decision == VERDICT_REINDEX_BY_VERSION for result in results):
        return 2
    return 0


def run_verify(args: argparse.Namespace, options: ConnectionOptions) -> int:
    from .amcheck import verify_databases

    databases = resolve_databases(args, options)
    results = verify_databases(
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
    )
    write_verify_report(results, args.format, args.output)
    if args.strict_exit_code and any(result.status == AMCHECK_FAILED for result in results):
        return 2
    return 0


def run_compare(args: argparse.Namespace, options: ConnectionOptions) -> int:
    from .compare import compare_databases

    databases = resolve_databases(args, options)
    results = compare_databases(
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
    )
    write_compare_report(results, args.format, args.output)
    if args.strict_exit_code and any(
        result.final_decision in (VERDICT_REINDEX_BY_BOTH, VERDICT_REINDEX_BY_AMCHECK, VERDICT_REINDEX_BY_VERSION)
        for result in results
    ):
        return 2
    return 0


def run_plan_reindex(args: argparse.Namespace, options: ConnectionOptions) -> int:
    databases = resolve_databases(args, options)
    results = scan_databases(
        options=options,
        databases=databases,
        provider=args.provider,
        schema=args.schema,
        include_system=args.include_system,
        largest=args.largest,
    )
    if args.output:
        write_scan_report(results, args.format, args.output)
    write_reindex_plan(results, args.sql_output)
    if args.strict_exit_code and any(result.decision == VERDICT_REINDEX_BY_VERSION for result in results):
        return 2
    return 0


def resolve_databases(args: argparse.Namespace, options: ConnectionOptions) -> list[str]:
    if args.all_databases:
        return list_databases(options, args.maintenance_db)
    return [args.database or args.maintenance_db]
