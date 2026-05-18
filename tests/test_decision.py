import unittest

from pgcollcheck.decision import classify_collation_version, decide_scan_result
from pgcollcheck.models import (
    SCAN_OK,
    SCAN_OK_UNVERSIONED,
    SCAN_UNKNOWN_NO_ACTUAL_VERSION,
    SCAN_UNKNOWN_NO_STORED_VERSION,
    SCAN_VERSION_MISMATCH,
    VERDICT_OK,
    VERDICT_REINDEX_BY_VERSION,
    VERDICT_UNKNOWN,
)


class ImportTest(unittest.TestCase):
    def test_project_imports(self) -> None:
        import pgcollcheck

        self.assertEqual(pgcollcheck.__version__, "0.1.0")


class DecisionTest(unittest.TestCase):
    def test_matching_versions_are_ok(self) -> None:
        self.assertEqual(classify_collation_version("2.39", "2.39"), SCAN_OK)

    def test_unversioned_collation_is_ok_unversioned(self) -> None:
        self.assertEqual(classify_collation_version(None, None), SCAN_OK_UNVERSIONED)

    def test_different_versions_need_reindex(self) -> None:
        status = classify_collation_version("2.38", "2.39")

        self.assertEqual(status, SCAN_VERSION_MISMATCH)
        self.assertEqual(decide_scan_result([status]), VERDICT_REINDEX_BY_VERSION)

    def test_missing_versions_are_unknown(self) -> None:
        self.assertEqual(classify_collation_version(None, "2.39"), SCAN_UNKNOWN_NO_STORED_VERSION)
        self.assertEqual(classify_collation_version("2.39", None), SCAN_UNKNOWN_NO_ACTUAL_VERSION)
        self.assertEqual(decide_scan_result([SCAN_UNKNOWN_NO_STORED_VERSION]), VERDICT_UNKNOWN)
        self.assertEqual(decide_scan_result([SCAN_UNKNOWN_NO_ACTUAL_VERSION]), VERDICT_UNKNOWN)

    def test_ok_statuses_make_ok_index(self) -> None:
        self.assertEqual(decide_scan_result([SCAN_OK, SCAN_OK_UNVERSIONED]), VERDICT_OK)


if __name__ == "__main__":
    unittest.main()
