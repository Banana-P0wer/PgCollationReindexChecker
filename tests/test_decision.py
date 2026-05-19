import unittest

from pgcollcheck.decision import classify_collation_version, decide_compare_result, decide_scan_result
from pgcollcheck.models import (
    AMCHECK_FAILED,
    AMCHECK_OK,
    AMCHECK_SKIPPED_EXTENSION_MISSING,
    SCAN_OK,
    SCAN_OK_UNVERSIONED,
    SCAN_UNKNOWN_NO_ACTUAL_VERSION,
    SCAN_UNKNOWN_NO_STORED_VERSION,
    SCAN_VERSION_MISMATCH,
    VERDICT_OK,
    VERDICT_REINDEX_BY_AMCHECK,
    VERDICT_REINDEX_BY_BOTH,
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

    def test_compare_ok_when_catalog_and_amcheck_are_ok(self) -> None:
        decision, _ = decide_compare_result(VERDICT_OK, AMCHECK_OK)

        self.assertEqual(decision, VERDICT_OK)

    def test_compare_prefers_version_reindex_when_amcheck_passes(self) -> None:
        decision, _ = decide_compare_result(VERDICT_REINDEX_BY_VERSION, AMCHECK_OK)

        self.assertEqual(decision, VERDICT_REINDEX_BY_VERSION)

    def test_compare_reports_both_when_both_methods_fail(self) -> None:
        decision, _ = decide_compare_result(VERDICT_REINDEX_BY_VERSION, AMCHECK_FAILED)

        self.assertEqual(decision, VERDICT_REINDEX_BY_BOTH)

    def test_compare_reports_amcheck_only_failure(self) -> None:
        decision, _ = decide_compare_result(VERDICT_OK, AMCHECK_FAILED)

        self.assertEqual(decision, VERDICT_REINDEX_BY_AMCHECK)

    def test_compare_is_unknown_when_amcheck_is_skipped(self) -> None:
        decision, _ = decide_compare_result(VERDICT_OK, AMCHECK_SKIPPED_EXTENSION_MISSING)

        self.assertEqual(decision, VERDICT_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
