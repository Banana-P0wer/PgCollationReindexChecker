from __future__ import annotations

import argparse
import os
import sys

from .db import ConnectionOptions
from .discovery import listDatabases
from .errors import PgCollCheckError
from .exit_codes import ERROR, OK, PARTIAL_FAILURE, REINDEX_RECOMMENDED, UNKNOWN
from .models import (
    AMCHECK_FAILED,
    VERDICT_REINDEX_BY_AMCHECK,
    VERDICT_REINDEX_BY_BOTH,
    VERDICT_REINDEX_BY_VERSION,
)
from .progress import ProgressReporter
from .reports import writeCompareReport, writeReindexPlan, writeScanReport, writeVerifyReport
from .scanner import scanDatabasesWithFailures
from .server import ensureSupportedPostgres


def main(argv: list[str] | None = None) -> int:
    parser = buildParser()
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
            ensureSupportedPostgres(options, versionCheckDatabase(args))
        if args.command == "scan":
            return runScan(args, options)
        if args.command == "verify":
            return runVerify(args, options)
        if args.command == "compare":
            return runCompare(args, options)
        if args.command == "plan-reindex":
            return runPlanReindex(args, options)
    except PgCollCheckError as exc:
        print(f"pgcollcheck: {exc}", file=sys.stderr)
        return ERROR
    except Exception as exc:
        print(f"pgcollcheck: {exc}", file=sys.stderr)
        return ERROR

    parser.print_help()
    return ERROR


def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgcollcheck",
        description="Check PostgreSQL collation versions used by string indexes.",
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", parents=[connectionParent()], help="compare stored and actual collation versions")
    addScanArgs(scan, includeAccessMethod=True)

    verify = subparsers.add_parser("verify", parents=[connectionParent()], help="run amcheck for B-tree indexes with collatable keys")
    addVerifyArgs(verify)

    compare = subparsers.add_parser("compare", parents=[connectionParent()], help="combine catalog scan and amcheck verification")
    addCompareArgs(compare)

    plan = subparsers.add_parser("plan-reindex", parents=[connectionParent()], help="generate SQL commands for indexes that need REINDEX")
    addScanArgs(plan, includeAccessMethod=True)
    plan.add_argument("--sql-output", dest="sqlOutput", help="Write generated SQL to this file.")

    return parser


def connectionParent() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="PostgreSQL DSN.")
    parser.add_argument("--host", help="Database host.")
    parser.add_argument("--port", type=int, help="Database port.")
    parser.add_argument("--user", help="Database user.")
    parser.add_argument("--password", help="Database password.")
    parser.add_argument(
        "--maintenance-db",
        dest="maintenanceDb",
        default=os.environ.get("PGDATABASE") or "postgres",
        help="Database used to discover all databases. Default: postgres.",
    )
    parser.add_argument("--progress", action="store_true", help="Print progress messages to stderr.")
    return parser


def addScanArgs(parser: argparse.ArgumentParser, includeAccessMethod: bool = False) -> None:
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--database", help="Scan one database. Defaults to --maintenance-db.")
    target.add_argument("--all-databases", dest="allDatabases", action="store_true", help="Scan every non-template database.")
    parser.add_argument("--schema", help="Limit scan to one schema.")
    parser.add_argument(
        "--provider",
        choices=("all", "libc", "icu", "builtin"),
        default="all",
        help="Limit by effective collation provider.",
    )
    if includeAccessMethod:
        parser.add_argument(
            "--access-method",
            dest="accessMethod",
            choices=("btree", "all"),
            default="btree",
            help="Limit catalog scan by index access method. Default: btree.",
        )
    parser.add_argument("--include-system", dest="includeSystem", action="store_true", help="Include pg_catalog and other system schemas.")
    parser.add_argument(
        "--largest",
        type=positiveInt,
        help="Show N largest safe indexes per database, while always keeping REINDEX and UNKNOWN results.",
    )
    parser.add_argument("--only-mismatches", dest="onlyMismatches", action="store_true", help="Only show indexes that need REINDEX or have UNKNOWN status.")
    parser.add_argument("--format", choices=("table", "json"), default="table", help="Report format.")
    parser.add_argument("--output", help="Write report to this file.")
    parser.add_argument("--strict-exit-code", dest="strictExitCode", action="store_true", help="Return code 2 when REINDEX is recommended.")


def addVerifyArgs(parser: argparse.ArgumentParser) -> None:
    addScanArgs(parser)
    parser.add_argument(
        "--mode",
        choices=("quick", "normal", "deep"),
        default="normal",
        help="amcheck mode. quick skips heapallindexed, deep uses bt_index_parent_check.",
    )
    parser.add_argument("--install-extension", dest="installExtension", action="store_true", help="Create amcheck if it is missing.")
    parser.add_argument("--lock-timeout", dest="lockTimeout", default="5s", help="PostgreSQL lock_timeout for amcheck.")
    parser.add_argument("--statement-timeout", dest="statementTimeout", default="30min", help="PostgreSQL statement_timeout for amcheck.")


def addCompareArgs(parser: argparse.ArgumentParser) -> None:
    addScanArgs(parser)
    parser.add_argument(
        "--verify-mode",
        dest="verifyMode",
        choices=("quick", "normal", "deep"),
        default="normal",
        help="amcheck mode used by compare.",
    )
    parser.add_argument("--install-extension", dest="installExtension", action="store_true", help="Create amcheck if it is missing.")
    parser.add_argument("--lock-timeout", dest="lockTimeout", default="5s", help="PostgreSQL lock_timeout for amcheck.")
    parser.add_argument("--statement-timeout", dest="statementTimeout", default="30min", help="PostgreSQL statement_timeout for amcheck.")


def runScan(args: argparse.Namespace, options: ConnectionOptions) -> int:
    databases = resolveDatabases(args, options)
    results, failures = scanDatabasesWithFailures(
        options=options,
        databases=databases,
        provider=args.provider,
        accessMethod=args.accessMethod,
        schema=args.schema,
        includeSystem=args.includeSystem,
        largest=args.largest,
        progress=ProgressReporter(args.progress),
        continueOnError=args.allDatabases,
    )
    results = filterScanResults(results, args.onlyMismatches)
    writeScanReport(
        results,
        args.format,
        args.output,
        onlyMismatches=args.onlyMismatches,
        failures=failures,
        scope=reportScope(args, databases),
    )
    return commandExitCode(args.strictExitCode, [result.decision for result in results], failures)


def runVerify(args: argparse.Namespace, options: ConnectionOptions) -> int:
    from .amcheck import verifyDatabasesWithFailures

    databases = resolveDatabases(args, options)
    results, failures = verifyDatabasesWithFailures(
        options=options,
        databases=databases,
        mode=args.mode,
        provider=args.provider,
        schema=args.schema,
        includeSystem=args.includeSystem,
        largest=args.largest,
        installExtension=args.installExtension,
        lockTimeout=args.lockTimeout,
        statementTimeout=args.statementTimeout,
        progress=ProgressReporter(args.progress),
        continueOnError=args.allDatabases,
    )
    results = filterAmcheckResults(results, args.onlyMismatches)
    writeVerifyReport(
        results,
        args.format,
        args.output,
        onlyMismatches=args.onlyMismatches,
        failures=failures,
        scope=reportScope(args, databases),
    )
    if failures:
        return PARTIAL_FAILURE
    if args.strictExitCode and any(result.status == AMCHECK_FAILED for result in results):
        return REINDEX_RECOMMENDED
    if args.strictExitCode and any(result.status != "AMCHECK_OK" for result in results):
        return UNKNOWN
    return OK


def runCompare(args: argparse.Namespace, options: ConnectionOptions) -> int:
    from .compare import compareDatabasesWithFailures

    databases = resolveDatabases(args, options)
    results, failures = compareDatabasesWithFailures(
        options=options,
        databases=databases,
        provider=args.provider,
        schema=args.schema,
        includeSystem=args.includeSystem,
        largest=args.largest,
        verifyMode=args.verifyMode,
        installExtension=args.installExtension,
        lockTimeout=args.lockTimeout,
        statementTimeout=args.statementTimeout,
        progress=ProgressReporter(args.progress),
        continueOnError=args.allDatabases,
    )
    results = filterCompareResults(results, args.onlyMismatches)
    writeCompareReport(
        results,
        args.format,
        args.output,
        onlyMismatches=args.onlyMismatches,
        failures=failures,
        scope=reportScope(args, databases),
    )
    if failures:
        return PARTIAL_FAILURE
    if args.strictExitCode and any(
        result.finalDecision in (VERDICT_REINDEX_BY_BOTH, VERDICT_REINDEX_BY_AMCHECK, VERDICT_REINDEX_BY_VERSION)
        for result in results
    ):
        return REINDEX_RECOMMENDED
    return scanExitCode(args.strictExitCode, [result.finalDecision for result in results])


def runPlanReindex(args: argparse.Namespace, options: ConnectionOptions) -> int:
    databases = resolveDatabases(args, options)
    results, failures = scanDatabasesWithFailures(
        options=options,
        databases=databases,
        provider=args.provider,
        schema=args.schema,
        includeSystem=args.includeSystem,
        largest=args.largest,
        progress=ProgressReporter(args.progress),
        continueOnError=args.allDatabases,
    )
    results = filterScanResults(results, args.onlyMismatches)
    if args.output:
        writeScanReport(
            results,
            args.format,
            args.output,
            onlyMismatches=args.onlyMismatches,
            failures=failures,
            scope=reportScope(args, databases),
        )
    writeReindexPlan(results, args.sqlOutput, includeDatabaseSwitches=args.allDatabases)
    return commandExitCode(args.strictExitCode, [result.decision for result in results], failures)


def resolveDatabases(args: argparse.Namespace, options: ConnectionOptions) -> list[str]:
    if args.allDatabases:
        return listDatabases(options, args.maintenanceDb)
    return [args.database or args.maintenanceDb]


def versionCheckDatabase(args: argparse.Namespace) -> str:
    if getattr(args, "allDatabases", False):
        return args.maintenanceDb
    return getattr(args, "database", None) or args.maintenanceDb


def scanExitCode(strict: bool, decisions: list[str]) -> int:
    if not strict:
        return OK
    if any("REINDEX" in decision for decision in decisions):
        return REINDEX_RECOMMENDED
    if any(decision == "UNKNOWN" for decision in decisions):
        return UNKNOWN
    return OK


def commandExitCode(strict: bool, decisions: list[str], failures: list | None = None) -> int:
    if failures:
        return PARTIAL_FAILURE
    return scanExitCode(strict, decisions)


def reportScope(args: argparse.Namespace, databases: list[str]) -> dict[str, object]:
    scope: dict[str, object] = {
        "databases": databases,
        "schema": getattr(args, "schema", None),
        "provider": getattr(args, "provider", None),
        "include_system": getattr(args, "includeSystem", False),
        "largest": getattr(args, "largest", None),
        "only_mismatches": getattr(args, "onlyMismatches", False),
        "all_databases": getattr(args, "allDatabases", False),
    }
    optionalScopeFields = {
        "accessMethod": "access_method",
        "mode": "mode",
        "verifyMode": "verify_mode",
    }
    for attrName, scopeName in optionalScopeFields.items():
        if hasattr(args, attrName):
            scope[scopeName] = getattr(args, attrName)
    return scope


def positiveInt(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def filterScanResults(results, onlyMismatches: bool):
    if not onlyMismatches:
        return results
    return [
        result
        for result in results
        if "REINDEX" in result.decision or result.decision == "UNKNOWN"
    ]


def filterAmcheckResults(results, onlyMismatches: bool):
    if not onlyMismatches:
        return results
    return [
        result
        for result in results
        if result.status != "AMCHECK_OK"
    ]


def filterCompareResults(results, onlyMismatches: bool):
    if not onlyMismatches:
        return results
    return [
        result
        for result in results
        if result.finalDecision != "OK"
    ]
