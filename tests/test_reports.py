import tempfile
import unittest
import json
from pathlib import Path

from pgcollcheck.models import AMCHECK_OK, AmcheckResult, ScanResult, quoteQualifiedName
from pgcollcheck.reports import formatScanTable, formatVerifyTable, writeReindexPlan


def scanResult(databaseName: str, indexName: str) -> ScanResult:
    return ScanResult(
        databaseName=databaseName,
        indexOid=1,
        indexSchema="public",
        indexName=indexName,
        tableSchema="public",
        tableName="sample",
        accessMethod="btree",
        indexSizeBytes=8192,
        isUnique=False,
        isValid=True,
        isReady=True,
        indexDefinition="",
        reindexSql=f"REINDEX INDEX CONCURRENTLY public.{indexName};",
        decision="REINDEX_RECOMMENDED_BY_COLLATION_VERSION",
    )


class ReindexPlanTest(unittest.TestCase):
    def testQuoteQualifiedNameEscapesIdentifierParts(self) -> None:
        self.assertEqual(
            quoteQualifiedName('Odd Schema', 'idx"name'),
            '"Odd Schema"."idx""name"',
        )

    def testPlanReindexCanGroupCommandsByDatabase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "reindex.sql"
            writeReindexPlan(
                [scanResult("appdb", "users_name_idx"), scanResult("audit-db", "events_name_idx")],
                str(output),
                includeDatabaseSwitches=True,
            )

            text = output.read_text(encoding="utf-8")

        self.assertIn("\\connect appdb", text)
        self.assertIn('\\connect "audit-db"', text)
        self.assertIn("REINDEX INDEX CONCURRENTLY public.users_name_idx;", text)
        self.assertIn("REINDEX INDEX CONCURRENTLY public.events_name_idx;", text)

    def testOnlyMismatchesEmptyScanMessageIsSpecific(self) -> None:
        text = formatScanTable([], onlyMismatches=True)

        self.assertIn("No collation version mismatches", text)

    def testVerifyReportExplainsAmcheckCost(self) -> None:
        text = formatVerifyTable([amcheckResult("users_name_idx")])

        self.assertIn("Cost note", text)
        self.assertIn("amcheck reads index pages", text)

    def testJsonScanReportUsesEnvelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "scan.json"
            from pgcollcheck.reports import writeScanReport

            writeScanReport(
                [scanResult("appdb", "users_name_idx")],
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

def amcheckResult(indexName: str) -> AmcheckResult:
    return AmcheckResult(
        databaseName="appdb",
        indexOid=1,
        indexSchema="public",
        indexName=indexName,
        tableSchema="public",
        tableName="users",
        indexSizeBytes=8192,
        mode="normal",
        status=AMCHECK_OK,
        durationMs=1,
        reindexSql=f"REINDEX INDEX CONCURRENTLY public.{indexName};",
        indexDefinition="",
    )


if __name__ == "__main__":
    unittest.main()
