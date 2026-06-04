import unittest
from unittest.mock import patch

from pgcollcheck.errors import DatabaseOperationError
from pgcollcheck.scanner import scan_databases_with_failures


class PartialFailureTest(unittest.TestCase):
    def test_all_database_scan_continues_after_database_error(self) -> None:
        calls: list[str] = []

        def fake_scan_database(**kwargs):
            database = kwargs["database"]
            calls.append(database)
            if database == "broken_db":
                raise RuntimeError("connection failed")
            return []

        with patch("pgcollcheck.scanner.scan_database", side_effect=fake_scan_database):
            results, failures = scan_databases_with_failures(
                options=object(),
                databases=["broken_db", "healthy_db"],
                continue_on_error=True,
            )

        self.assertEqual(results, [])
        self.assertEqual(calls, ["broken_db", "healthy_db"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].database_name, "broken_db")
        self.assertEqual(failures[0].command, "scan")
        self.assertIn("connection failed", failures[0].message)

    def test_single_database_scan_raises_typed_operation_error(self) -> None:
        with patch("pgcollcheck.scanner.scan_database", side_effect=RuntimeError("connection failed")):
            with self.assertRaises(DatabaseOperationError) as raised:
                scan_databases_with_failures(
                    options=object(),
                    databases=["broken_db"],
                    continue_on_error=False,
                )

        self.assertEqual(raised.exception.database_name, "broken_db")
        self.assertEqual(raised.exception.command, "scan")
        self.assertEqual(raised.exception.error_type, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
