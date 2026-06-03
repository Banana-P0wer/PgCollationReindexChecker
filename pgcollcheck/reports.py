from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .models import AmcheckResult, CompareResult, DatabaseFailure, ScanResult


def human_size(size: int | None) -> str:
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


def write_scan_report(
    results: list[ScanResult],
    output_format: str,
    output: str | None = None,
    only_mismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
    scope: dict[str, Any] | None = None,
) -> None:
    failures = failures or []
    if output_format == "json":
        write_text(
            json.dumps(
                build_json_report(
                    command="scan",
                    results=[result.to_dict() for result in results],
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
    write_text(format_scan_table(results, only_mismatches, failures), output)


def write_verify_report(
    results: list[AmcheckResult],
    output_format: str,
    output: str | None = None,
    only_mismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
    scope: dict[str, Any] | None = None,
) -> None:
    failures = failures or []
    if output_format == "json":
        write_text(
            json.dumps(
                build_json_report(
                    command="verify",
                    results=[result.to_dict() for result in results],
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
    write_text(format_verify_table(results, only_mismatches, failures), output)


def write_compare_report(
    results: list[CompareResult],
    output_format: str,
    output: str | None = None,
    only_mismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
    scope: dict[str, Any] | None = None,
) -> None:
    failures = failures or []
    if output_format == "json":
        write_text(
            json.dumps(
                build_json_report(
                    command="compare",
                    results=[result.to_dict() for result in results],
                    failures=failures,
                    scope=scope,
                    summary={
                        "reindex_count": sum(1 for result in results if "REINDEX" in result.final_decision),
                        "unknown_count": sum(1 for result in results if result.final_decision == "UNKNOWN"),
                    },
                ),
                ensure_ascii=False,
                indent=2,
            ),
            output,
        )
        return
    write_text(format_compare_table(results, only_mismatches, failures), output)


def build_json_report(
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
        "failures": [failure.to_dict() for failure in failures],
    }


def format_scan_table(
    results: list[ScanResult],
    only_mismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
) -> str:
    failures = failures or []
    if not results:
        failure_text = format_failures(failures)
        if only_mismatches:
            return "No collation version mismatches or UNKNOWN states were found.\n" + failure_text
        return "No B-tree indexes with collatable keys were found.\n" + failure_text

    table_rows: list[dict[str, str]] = []
    for result in results:
        table_rows.append(
            {
                "database": result.database_name,
                "index": result.quoted_qualified_index,
                "table": result.quoted_qualified_table,
                "size": human_size(result.index_size_bytes),
                "collations": format_collations(result),
                "decision": result.decision,
            }
        )

    text = render_table(table_rows, ["database", "index", "table", "size", "collations", "decision"])
    reindex_commands = [result.reindex_sql for result in results if "REINDEX" in result.decision]
    unknown_results = [result for result in results if result.decision == "UNKNOWN"]

    lines = [text, ""]
    if reindex_commands:
        lines.append("REINDEX commands:")
        lines.extend(f"  {command}" for command in reindex_commands)
    else:
        lines.append("No collation version mismatches were found.")

    if unknown_results:
        lines.append("")
        lines.append("Indexes with unknown version state:")
        lines.extend(f"  {result.database_name}: {result.qualified_index}" for result in unknown_results)

    return "\n".join(lines) + "\n" + format_failures(failures)


def format_verify_table(
    results: list[AmcheckResult],
    only_mismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
) -> str:
    failures = failures or []
    if not results:
        failure_text = format_failures(failures)
        if only_mismatches:
            return "No amcheck failures, skipped checks, or UNKNOWN states were found.\n" + failure_text
        return "No B-tree indexes with collatable keys were found.\n" + failure_text

    table_rows = [
        {
            "database": result.database_name,
            "index": result.quoted_qualified_index,
            "table": result.quoted_qualified_table,
            "size": human_size(result.index_size_bytes),
            "mode": result.mode,
            "status": result.status,
            "duration": "" if result.duration_ms is None else f"{result.duration_ms} ms",
            "error": compact_error(result.error_message),
        }
        for result in results
    ]
    text = render_table(table_rows, ["database", "index", "table", "size", "mode", "status", "duration", "error"])
    failed = [result for result in results if result.status == "AMCHECK_FAILED"]
    skipped = [result for result in results if result.status.startswith("SKIPPED")]

    lines = [text, ""]
    lines.append(cost_note("amcheck", len(results)))
    lines.append("")
    if failed:
        lines.append("Indexes that should be rebuilt after amcheck failure:")
        lines.extend(f"  {result.reindex_sql}" for result in failed)
    else:
        lines.append("No amcheck B-tree failures were reported.")

    if skipped:
        lines.append("")
        lines.append("Skipped checks:")
        lines.extend(f"  {result.database_name}: {result.qualified_index} ({result.status})" for result in skipped)

    return "\n".join(lines) + "\n" + format_failures(failures)


def format_compare_table(
    results: list[CompareResult],
    only_mismatches: bool = False,
    failures: list[DatabaseFailure] | None = None,
) -> str:
    failures = failures or []
    if not results:
        failure_text = format_failures(failures)
        if only_mismatches:
            return "No final REINDEX or UNKNOWN verdicts were produced.\n" + failure_text
        return "No B-tree indexes with collatable keys were found.\n" + failure_text

    table_rows = [
        {
            "database": result.scan.database_name,
            "index": result.scan.quoted_qualified_index,
            "catalog": result.scan.decision,
            "amcheck": result.amcheck.status if result.amcheck else "",
            "final": result.final_decision,
            "reason": result.reason,
        }
        for result in results
    ]
    text = render_table(table_rows, ["database", "index", "catalog", "amcheck", "final", "reason"])
    reindex_commands = [
        result.scan.reindex_sql
        for result in results
        if "REINDEX" in result.final_decision
    ]

    lines = [text, ""]
    amcheck_count = sum(1 for result in results if result.amcheck is not None)
    lines.append(cost_note("compare", amcheck_count))
    lines.append("")
    if reindex_commands:
        lines.append("REINDEX commands:")
        lines.extend(f"  {command}" for command in reindex_commands)
    else:
        lines.append("No final REINDEX verdicts were produced.")
    return "\n".join(lines) + "\n" + format_failures(failures)


def format_failures(failures: list[DatabaseFailure]) -> str:
    if not failures:
        return ""
    rows = [
        {
            "database": failure.database_name,
            "command": failure.command,
            "error": compact_error(failure.message),
        }
        for failure in failures
    ]
    return "\nPartial failures:\n" + render_table(rows, ["database", "command", "error"]) + "\n"


def cost_note(command: str, index_count: int) -> str:
    return (
        f"Cost note: {command} ran amcheck for {index_count} index(es); "
        "amcheck reads index pages and can wait for PostgreSQL locks."
    )


def format_collations(result: ScanResult) -> str:
    parts: list[str] = []
    for dependency in result.dependencies:
        key_label = dependency.key_name
        if dependency.key_name in ("<expression>", "<index dependency>"):
            key_label = dependency.key_expression
        name = dependency.quoted_qualified_collation
        provider = dependency.provider_name
        status = dependency.status
        if dependency.stored_version is None and dependency.actual_version is None:
            version = "unversioned"
        else:
            version = f"{dependency.stored_version or '?'}->{dependency.actual_version or '?'}"
        parts.append(f"{key_label}:{name}/{provider}/{version}/{status}")
    return "; ".join(parts)


def compact_error(message: str | None) -> str:
    if not message:
        return ""
    first_line = message.splitlines()[0]
    if len(first_line) > 90:
        return first_line[:87] + "..."
    return first_line


def render_table(rows: list[dict[str, str]], columns: list[str]) -> str:
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


def write_reindex_plan(
    results: Iterable[ScanResult],
    output: str | None = None,
    include_database_switches: bool = False,
) -> None:
    result_list = list(results)
    lines = [
        "-- Generated by pgcollcheck.",
        "-- Run REINDEX first. Run REFRESH VERSION only after successful rebuild.",
        "",
    ]
    refresh_commands: list[str] = []
    seen_refresh: set[str] = set()

    current_database: str | None = None
    for result in result_list:
        if "REINDEX" not in result.decision:
            continue
        if include_database_switches and result.database_name != current_database:
            if current_database is not None:
                lines.append("")
            current_database = result.database_name
            lines.append(f"-- Database: {result.database_name}")
            lines.append(f"\\connect {quote_psql_argument(result.database_name)}")
            lines.append("")
        lines.append(result.reindex_sql)
        for command in result.refresh_sql:
            if command not in seen_refresh:
                seen_refresh.add(command)
                refresh_commands.append(command)

    if refresh_commands:
        lines.extend(["", "-- After successful REINDEX:", *refresh_commands])
    if len(lines) == 3:
        lines.append("-- No REINDEX commands are required by the current scan.")
    write_text("\n".join(lines) + "\n", output)


def quote_psql_argument(value: str) -> str:
    if value.replace("_", "").isalnum():
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_text(text: str, output: str | None = None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)
