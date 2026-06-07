import unittest

from pgcollcheck.cli import filterScanResults
from pgcollcheck.decision import classifyCollationVersion, decideCompareResult, decideScanResult
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
from pgcollcheck.scanner import limitScanResults


class ImportTest(unittest.TestCase):
    def testProjectImports(self) -> None:
        import pgcollcheck

        self.assertEqual(pgcollcheck.__version__, "0.1.0")


class DecisionTest(unittest.TestCase):
    def testMatchingVersionsAreOk(self) -> None:
        self.assertEqual(classifyCollationVersion("2.39", "2.39"), SCAN_OK)

    def testUnversionedCollationIsOkUnversioned(self) -> None:
        self.assertEqual(classifyCollationVersion(None, None), SCAN_OK_UNVERSIONED)

    def testDifferentVersionsNeedReindex(self) -> None:
        status = classifyCollationVersion("2.38", "2.39")

        self.assertEqual(status, SCAN_VERSION_MISMATCH)
        self.assertEqual(decideScanResult([status]), VERDICT_REINDEX_BY_VERSION)

    def testMissingVersionsAreUnknown(self) -> None:
        self.assertEqual(classifyCollationVersion(None, "2.39"), SCAN_UNKNOWN_NO_STORED_VERSION)
        self.assertEqual(classifyCollationVersion("2.39", None), SCAN_UNKNOWN_NO_ACTUAL_VERSION)
        self.assertEqual(decideScanResult([SCAN_UNKNOWN_NO_STORED_VERSION]), VERDICT_UNKNOWN)
        self.assertEqual(decideScanResult([SCAN_UNKNOWN_NO_ACTUAL_VERSION]), VERDICT_UNKNOWN)

    def testOkStatusesMakeOkIndex(self) -> None:
        self.assertEqual(decideScanResult([SCAN_OK, SCAN_OK_UNVERSIONED]), VERDICT_OK)

    def testCompareOkWhenCatalogAndAmcheckAreOk(self) -> None:
        decision, _ = decideCompareResult(VERDICT_OK, AMCHECK_OK)

        self.assertEqual(decision, VERDICT_OK)

    def testComparePrefersVersionReindexWhenAmcheckPasses(self) -> None:
        decision, _ = decideCompareResult(VERDICT_REINDEX_BY_VERSION, AMCHECK_OK)

        self.assertEqual(decision, VERDICT_REINDEX_BY_VERSION)

    def testCompareReportsBothWhenBothMethodsFail(self) -> None:
        decision, _ = decideCompareResult(VERDICT_REINDEX_BY_VERSION, AMCHECK_FAILED)

        self.assertEqual(decision, VERDICT_REINDEX_BY_BOTH)

    def testCompareReportsAmcheckOnlyFailure(self) -> None:
        decision, _ = decideCompareResult(VERDICT_OK, AMCHECK_FAILED)

        self.assertEqual(decision, VERDICT_REINDEX_BY_AMCHECK)

    def testCompareIsUnknownWhenAmcheckIsSkipped(self) -> None:
        decision, _ = decideCompareResult(VERDICT_OK, AMCHECK_SKIPPED_EXTENSION_MISSING)

        self.assertEqual(decision, VERDICT_UNKNOWN)

    def testCompareIsUnknownWhenAmcheckPermissionIsMissing(self) -> None:
        decision, _ = decideCompareResult(VERDICT_OK, AMCHECK_SKIPPED_PERMISSION_DENIED)

        self.assertEqual(decision, VERDICT_UNKNOWN)

    def testOnlyMismatchesFiltersOkScanResults(self) -> None:
        ok = makeScanResult("ok_idx", VERDICT_OK)
        reindex = makeScanResult("reindex_idx", VERDICT_REINDEX_BY_VERSION)
        unknown = makeScanResult("unknown_idx", VERDICT_UNKNOWN)

        filtered = filterScanResults([ok, reindex, unknown], onlyMismatches=True)

        self.assertEqual([result.indexName for result in filtered], ["reindex_idx", "unknown_idx"])

    def testLargestLimitKeepsAllProblematicResults(self) -> None:
        okLarge = makeScanResult("ok_large_idx", VERDICT_OK, size=4096, oid=1)
        okSmall = makeScanResult("ok_small_idx", VERDICT_OK, size=1024, oid=2)
        reindexSmall = makeScanResult("reindex_small_idx", VERDICT_REINDEX_BY_VERSION, size=512, oid=3)

        limited = limitScanResults([okSmall, reindexSmall, okLarge], largest=1)

        self.assertEqual(
            [result.indexName for result in limited],
            ["reindex_small_idx", "ok_large_idx"],
        )


def makeScanResult(indexName: str, decision: str, size: int = 8192, oid: int = 1) -> ScanResult:
    return ScanResult(
        databaseName="testdb",
        indexOid=oid,
        indexSchema="public",
        indexName=indexName,
        tableSchema="public",
        tableName="sample",
        accessMethod="btree",
        indexSizeBytes=size,
        isUnique=False,
        isValid=True,
        isReady=True,
        indexDefinition="",
        reindexSql=f"REINDEX INDEX CONCURRENTLY public.{indexName};",
        decision=decision,
    )


if __name__ == "__main__":
    unittest.main()
