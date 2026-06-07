from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .models import AmcheckResult, CompareResult, DatabaseFailure, ScanResult


def humanSize(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def writeScanReport(
    results: list[ScanResult],
    outputFormat: str,
    output: str | None = None,
    onlyMismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
    scope: dict[str, Any] | None = None,
) -> None:
    failures = failures or []
    if outputFormat == "json":
        writeText(
            json.dumps(
                buildJsonReport(
                    command="scan",
                    results=[result.toDict() for result in results],
                    failures=failures,
                    scope=scope,
                    summary={
                        "reindex_count": sum(1 for result in results if "REINDEX" in result.decision),
                        "unknown_count": sum(1 for result in results if result.decision == "UNKNOWN"),
                    },
                ),
                ensure_ascii=False,
                indent=2,
            ),
            output,
        )
        return
    writeText(formatScanTable(results, onlyMismatches, failures), output)


def writeVerifyReport(
    results: list[AmcheckResult],
    outputFormat: str,
    output: str | None = None,
    onlyMismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
    scope: dict[str, Any] | None = None,
) -> None:
    failures = failures or []
    if outputFormat == "json":
        writeText(
            json.dumps(
                buildJsonReport(
                    command="verify",
                    results=[result.toDict() for result in results],
                    failures=failures,
                    scope=scope,
                    summary={
                        "amcheck_failed_count": sum(1 for result in results if result.status == "AMCHECK_FAILED"),
                        "amcheck_skipped_count": sum(1 for result in results if result.status.startswith("SKIPPED")),
                    },
                ),
                ensure_ascii=False,
                indent=2,
            ),
            output,
        )
        return
    writeText(formatVerifyTable(results, onlyMismatches, failures), output)


def writeCompareReport(
    results: list[CompareResult],
    outputFormat: str,
    output: str | None = None,
    onlyMismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
    scope: dict[str, Any] | None = None,
) -> None:
    failures = failures or []
    if outputFormat == "json":
        writeText(
            json.dumps(
                buildJsonReport(
                    command="compare",
                    results=[result.toDict() for result in results],
                    failures=failures,
                    scope=scope,
                    summary={
                        "reindex_count": sum(1 for result in results if "REINDEX" in result.finalDecision),
                        "unknown_count": sum(1 for result in results if result.finalDecision == "UNKNOWN"),
                    },
                ),
                ensure_ascii=False,
                indent=2,
            ),
            output,
        )
        return
    writeText(formatCompareTable(results, onlyMismatches, failures), output)


def buildJsonReport(
    command: str,
    results: list[dict[str, Any]],
    failures: list[DatabaseFailure],
    scope: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summary or {}
    return {
        "tool": {
            "name": "pgcollcheck",
            "version": __version__,
        },
        "command": command,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope or {},
        "summary": {
            "result_count": len(results),
            "failure_count": len(failures),
            "partial_failure": bool(failures),
            **summary,
        },
        "results": results,
        "failures": [failure.toDict() for failure in failures],
    }


def formatScanTable(
    results: list[ScanResult],
    onlyMismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
) -> str:
    failures = failures or []
    if not results:
        failureText = formatFailures(failures)
        if onlyMismatches:
            return "No collation version mismatches or UNKNOWN states were found.\n" + failureText
        return "No B-tree indexes with collatable keys were found.\n" + failureText

    tableRows: list[dict[str, str]] = []
    for result in results:
        tableRows.append(
            {
                "database": result.databaseName,
                "index": result.quotedQualifiedIndex,
                "table": result.quotedQualifiedTable,
                "size": humanSize(result.indexSizeBytes),
                "collations": formatCollations(result),
                "decision": result.decision,
            }
        )

    text = renderTable(tableRows, ["database", "index", "table", "size", "collations", "decision"])
    reindexCommands = [result.reindexSql for result in results if "REINDEX" in result.decision]
    unknownResults = [result for result in results if result.decision == "UNKNOWN"]

    lines = [text, ""]
    if reindexCommands:
        lines.append("REINDEX commands:")
        lines.extend(f"  {command}" for command in reindexCommands)
    else:
        lines.append("No collation version mismatches were found.")

    if unknownResults:
        lines.append("")
        lines.append("Indexes with unknown version state:")
        lines.extend(f"  {result.databaseName}: {result.qualifiedIndex}" for result in unknownResults)

    return "\n".join(lines) + "\n" + formatFailures(failures)


def formatVerifyTable(
    results: list[AmcheckResult],
    onlyMismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
) -> str:
    failures = failures or []
    if not results:
        failureText = formatFailures(failures)
        if onlyMismatches:
            return "No amcheck failures, skipped checks, or UNKNOWN states were found.\n" + failureText
        return "No B-tree indexes with collatable keys were found.\n" + failureText

    tableRows = [
        {
            "database": result.databaseName,
            "index": result.quotedQualifiedIndex,
            "table": result.quotedQualifiedTable,
            "size": humanSize(result.indexSizeBytes),
            "mode": result.mode,
            "status": result.status,
            "duration": "" if result.durationMs is None else f"{result.durationMs} ms",
            "error": compactError(result.errorMessage),
        }
        for result in results
    ]
    text = renderTable(tableRows, ["database", "index", "table", "size", "mode", "status", "duration", "error"])
    failed = [result for result in results if result.status == "AMCHECK_FAILED"]
    skipped = [result for result in results if result.status.startswith("SKIPPED")]

    lines = [text, ""]
    lines.append(costNote("amcheck", len(results)))
    lines.append("")
    if failed:
        lines.append("Indexes that should be rebuilt after amcheck failure:")
        lines.extend(f"  {result.reindexSql}" for result in failed)
    else:
        lines.append("No amcheck B-tree failures were reported.")

    if skipped:
        lines.append("")
        lines.append("Skipped checks:")
        lines.extend(f"  {result.databaseName}: {result.qualifiedIndex} ({result.status})" for result in skipped)

    return "\n".join(lines) + "\n" + formatFailures(failures)


def formatCompareTable(
    results: list[CompareResult],
    onlyMismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
) -> str:
    failures = failures or []
    if not results:
        failureText = formatFailures(failures)
        if onlyMismatches:
            return "No final REINDEX or UNKNOWN verdicts were produced.\n" + failureText
        return "No B-tree indexes with collatable keys were found.\n" + failureText

    tableRows = [
        {
            "database": result.scan.databaseName,
            "index": result.scan.quotedQualifiedIndex,
            "catalog": result.scan.decision,
            "amcheck": result.amcheck.status if result.amcheck else "",
            "final": result.finalDecision,
            "reason": result.reason,
        }
        for result in results
    ]
    text = renderTable(tableRows, ["database", "index", "catalog", "amcheck", "final", "reason"])
    reindexCommands = [
        result.scan.reindexSql
        for result in results
        if "REINDEX" in result.finalDecision
    ]

    lines = [text, ""]
    amcheckCount = sum(1 for result in results if result.amcheck is not None)
    lines.append(costNote("compare", amcheckCount))
    lines.append("")
    if reindexCommands:
        lines.append("REINDEX commands:")
        lines.extend(f"  {command}" for command in reindexCommands)
    else:
        lines.append("No final REINDEX verdicts were produced.")
    return "\n".join(lines) + "\n" + formatFailures(failures)


def formatFailures(failures: list[DatabaseFailure]) -> str:
    if not failures:
        return ""
    rows = [
        {
            "database": failure.databaseName,
            "command": failure.command,
            "error": compactError(failure.message),
        }
        for failure in failures
    ]
    return "\nPartial failures:\n" + renderTable(rows, ["database", "command", "error"]) + "\n"


def costNote(command: str, indexCount: int) -> str:
    if command == "amcheck":
        return (
            f"Cost note: amcheck checked {indexCount} index(es); "
            "amcheck reads index pages and can wait for PostgreSQL locks."
        )
    return (
        f"Cost note: {command} ran amcheck for {indexCount} index(es); "
        "amcheck reads index pages and can wait for PostgreSQL locks."
    )


def formatCollations(result: ScanResult) -> str:
    parts: list[str] = []
    for dependency in result.dependencies:
        keyLabel = dependency.keyName
        if dependency.keyName in ("<expression>", "<index dependency>"):
            keyLabel = dependency.keyExpression
        name = dependency.quotedQualifiedCollation
        provider = dependency.providerName
        status = dependency.status
        if dependency.storedVersion is None and dependency.actualVersion is None:
            version = "unversioned"
        else:
            version = f"{dependency.storedVersion or '?'}->{dependency.actualVersion or '?'}"
        parts.append(f"{keyLabel}:{name}/{provider}/{version}/{status}")
    return "; ".join(parts)


def compactError(message: str | None) -> str:
    if not message:
        return ""
    firstLine = message.splitlines()[0]
    if len(firstLine) > 90:
        return firstLine[:87] + "..."
    return firstLine


def renderTable(rows: list[dict[str, str]], columns: list[str]) -> str:
    widths = {
        column: max(len(column), *(len(row[column]) for row in rows))
        for column in columns
    }
    lines = [
        "  ".join(column.ljust(widths[column]) for column in columns),
        "  ".join("-" * widths[column] for column in columns),
    ]
    for row in rows:
        lines.append("  ".join(row[column].ljust(widths[column]) for column in columns))
    return "\n".join(lines)


def writeReindexPlan(
    results: Iterable[ScanResult],
    output: str | None = None,
    includeDatabaseSwitches: bool = False,
) -> None:
    resultList = list(results)
    lines = [
        "-- Generated by pgcollcheck.",
        "-- Run REINDEX first. Run REFRESH VERSION only after successful rebuild.",
        "",
    ]
    refreshCommands: list[str] = []
    seenRefresh: set[str] = set()

    currentDatabase: str | None = None
    for result in resultList:
        if "REINDEX" not in result.decision:
            continue
        if includeDatabaseSwitches and result.databaseName != currentDatabase:
            if currentDatabase is not None:
                lines.append("")
            currentDatabase = result.databaseName
            lines.append(f"-- Database: {result.databaseName}")
            lines.append(f"\\connect {quotePsqlArgument(result.databaseName)}")
            lines.append("")
        lines.append(result.reindexSql)
        for command in result.refreshSql:
            if command not in seenRefresh:
                seenRefresh.add(command)
                refreshCommands.append(command)

    if refreshCommands:
        lines.extend(["", "-- After successful REINDEX:", *refreshCommands])
    if len(lines) == 3:
        lines.append("-- No REINDEX commands are required by the current scan.")
    writeText("\n".join(lines) + "\n", output)


def quotePsqlArgument(value: str) -> str:
    if value.replace("_", "").isalnum():
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def writeText(text: str, output: str | None = None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)
