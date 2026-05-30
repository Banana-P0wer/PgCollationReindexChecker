import unittest

from pgcollcheck.cli import filter_scan_results
from pgcollcheck.decision import classify_collation_version, decide_compare_result, decide_scan_result
from pgcollcheck.models import (
    AMCHECK_FAILED,
    AMCHECK_OK,
    AMCHECK_SKIPPED_EXTENSION_MISSING,
    AMCHECK_SKIPPED_PERMISSION_DENIED,
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
    ScanResult,
)
from pgcollcheck.scanner import limit_scan_results


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

    def test_compare_is_unknown_when_amcheck_permission_is_missing(self) -> None:
        decision, _ = decide_compare_result(VERDICT_OK, AMCHECK_SKIPPED_PERMISSION_DENIED)

        self.assertEqual(decision, VERDICT_UNKNOWN)

    def test_only_mismatches_filters_ok_scan_results(self) -> None:
        ok = make_scan_result("ok_idx", VERDICT_OK)
        reindex = make_scan_result("reindex_idx", VERDICT_REINDEX_BY_VERSION)
        unknown = make_scan_result("unknown_idx", VERDICT_UNKNOWN)

        filtered = filter_scan_results([ok, reindex, unknown], only_mismatches=True)

        self.assertEqual([result.index_name for result in filtered], ["reindex_idx", "unknown_idx"])

    def test_largest_limit_keeps_all_problematic_results(self) -> None:
        ok_large = make_scan_result("ok_large_idx", VERDICT_OK, size=4096, oid=1)
        ok_small = make_scan_result("ok_small_idx", VERDICT_OK, size=1024, oid=2)
        reindex_small = make_scan_result("reindex_small_idx", VERDICT_REINDEX_BY_VERSION, size=512, oid=3)

        limited = limit_scan_results([ok_small, reindex_small, ok_large], largest=1)

        self.assertEqual(
            [result.index_name for result in limited],
            ["reindex_small_idx", "ok_large_idx"],
        )


def make_scan_result(index_name: str, decision: str, size: int = 8192, oid: int = 1) -> ScanResult:
    return ScanResult(
        database_name="testdb",
        index_oid=oid,
        index_schema="public",
        index_name=index_name,
        table_schema="public",
        table_name="sample",
        access_method="btree",
        index_size_bytes=size,
        is_unique=False,
        is_valid=True,
        is_ready=True,
        index_definition="",
        reindex_sql=f"REINDEX INDEX CONCURRENTLY public.{index_name};",
        decision=decision,
    )


if __name__ == "__main__":
    unittest.main()
