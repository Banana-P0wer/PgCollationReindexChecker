import tempfile
import unittest
import json
from pathlib import Path

from pgcollcheck.models import AMCHECK_OK, AmcheckResult, ScanResult, quote_qualified_name
from pgcollcheck.reports import format_scan_table, format_verify_table, write_reindex_plan


def scan_result(database_name: str, index_name: str) -> ScanResult:
    return ScanResult(
        database_name=database_name,
        index_oid=1,
        index_schema="public",
        index_name=index_name,
        table_schema="public",
        table_name="sample",
        access_method="btree",
        index_size_bytes=8192,
        is_unique=False,
        is_valid=True,
        is_ready=True,
        index_definition="",
        reindex_sql=f"REINDEX INDEX CONCURRENTLY public.{index_name};",
        decision="REINDEX_RECOMMENDED_BY_COLLATION_VERSION",
    )


class ReindexPlanTest(unittest.TestCase):
    def test_quote_qualified_name_escapes_identifier_parts(self) -> None:
        self.assertEqual(
            quote_qualified_name('Odd Schema', 'idx"name'),
            '"Odd Schema"."idx""name"',
        )

    def test_plan_reindex_can_group_commands_by_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "reindex.sql"
            write_reindex_plan(
                [scan_result("appdb", "users_name_idx"), scan_result("audit-db", "events_name_idx")],
                str(output),
                include_database_switches=True,
            )

            text = output.read_text(encoding="utf-8")

        self.assertIn("\\connect appdb", text)
        self.assertIn('\\connect "audit-db"', text)
        self.assertIn("REINDEX INDEX CONCURRENTLY public.users_name_idx;", text)
        self.assertIn("REINDEX INDEX CONCURRENTLY public.events_name_idx;", text)

    def test_only_mismatches_empty_scan_message_is_specific(self) -> None:
        text = format_scan_table([], only_mismatches=True)

        self.assertIn("No collation version mismatches", text)

    def test_verify_report_explains_amcheck_cost(self) -> None:
        text = format_verify_table([amcheck_result("users_name_idx")])

        self.assertIn("Cost note", text)
        self.assertIn("amcheck reads index pages", text)

    def test_json_scan_report_uses_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "scan.json"
            from pgcollcheck.reports import write_scan_report

            write_scan_report(
                [scan_result("appdb", "users_name_idx")],
                "json",
                str(output),
                scope={"databases": ["appdb"]},
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["tool"]["name"], "pgcollcheck")
        self.assertEqual(payload["command"], "scan")
        self.assertEqual(payload["scope"]["databases"], ["appdb"])
        self.assertEqual(payload["summary"]["result_count"], 1)
        self.assertEqual(payload["results"][0]["index_name"], "users_name_idx")

def amcheck_result(index_name: str) -> AmcheckResult:
    return AmcheckResult(
        database_name="appdb",
        index_oid=1,
        index_schema="public",
        index_name=index_name,
        table_schema="public",
        table_name="users",
        index_size_bytes=8192,
        mode="normal",
        status=AMCHECK_OK,
        duration_ms=1,
        reindex_sql=f"REINDEX INDEX CONCURRENTLY public.{index_name};",
        index_definition="",
    )


if __name__ == "__main__":
    unittest.main()
