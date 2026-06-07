import unittest
from unittest.mock import patch

from pgcollcheck.errors import DatabaseOperationError
from pgcollcheck.scanner import scanDatabasesWithFailures


class PartialFailureTest(unittest.TestCase):
    def testAllDatabaseScanContinuesAfterDatabaseError(self) -> None:
        calls: list[str] = []

        def fakeScanDatabase(**kwargs):
            database = kwargs["database"]
            calls.append(database)
            if database == "broken_db":
                raise RuntimeError("connection failed")
            return []

        with patch("pgcollcheck.scanner.scanDatabase", side_effect=fakeScanDatabase):
            results, failures = scanDatabasesWithFailures(
                options=object(),
                databases=["broken_db", "healthy_db"],
                continueOnError=True,
            )

        self.assertEqual(results, [])
        self.assertEqual(calls, ["broken_db", "healthy_db"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].databaseName, "broken_db")
        self.assertEqual(failures[0].command, "scan")
        self.assertIn("connection failed", failures[0].message)

    def testSingleDatabaseScanRaisesTypedOperationError(self) -> None:
        with patch("pgcollcheck.scanner.scanDatabase", side_effect=RuntimeError("connection failed")):
            with self.assertRaises(DatabaseOperationError) as raised:
                scanDatabasesWithFailures(
                    options=object(),
                    databases=["broken_db"],
                    continueOnError=False,
                )

        self.assertEqual(raised.exception.databaseName, "broken_db")
        self.assertEqual(raised.exception.command, "scan")
        self.assertEqual(raised.exception.errorType, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
