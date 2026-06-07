from __future__ import annotations

from .models import (
    AMCHECK_FAILED,
    AMCHECK_OK,
    AMCHECK_TIMEOUT,
    SCAN_UNKNOWN_NO_ACTUAL_VERSION,
    SCAN_UNKNOWN_NO_STORED_VERSION,
    SCAN_VERSION_MISMATCH,
    VERDICT_OK,
    VERDICT_REINDEX_BY_AMCHECK,
    VERDICT_REINDEX_BY_BOTH,
    VERDICT_REINDEX_BY_VERSION,
    VERDICT_UNKNOWN,
)


def classifyCollationVersion(
    storedVersion: str | None,
    actualVersion: str | None,
) -> str:
    from .models import (
        SCAN_OK,
        SCAN_OK_UNVERSIONED,
    )

    if storedVersion is None and actualVersion is None:
        return SCAN_OK_UNVERSIONED
    if storedVersion is None:
        return SCAN_UNKNOWN_NO_STORED_VERSION
    if actualVersion is None:
        return SCAN_UNKNOWN_NO_ACTUAL_VERSION
    if storedVersion != actualVersion:
        return SCAN_VERSION_MISMATCH
    return SCAN_OK


def decideScanResult(statuses: list[str]) -> str:
    if SCAN_VERSION_MISMATCH in statuses:
        return VERDICT_REINDEX_BY_VERSION
    if SCAN_UNKNOWN_NO_STORED_VERSION in statuses:
        return VERDICT_UNKNOWN
    if SCAN_UNKNOWN_NO_ACTUAL_VERSION in statuses:
        return VERDICT_UNKNOWN
    return VERDICT_OK


def decideCompareResult(scanDecision: str, amcheckStatus: str | None) -> tuple[str, str]:
    versionChanged = scanDecision == VERDICT_REINDEX_BY_VERSION
    amcheckFailed = amcheckStatus == AMCHECK_FAILED

    if versionChanged and amcheckFailed:
        return (
            VERDICT_REINDEX_BY_BOTH,
            "collation version changed and amcheck reported a B-tree problem",
        )
    if amcheckFailed:
        return (
            VERDICT_REINDEX_BY_AMCHECK,
            "amcheck reported a B-tree problem; cause may be collation or another index issue",
        )
    if versionChanged:
        return (
            VERDICT_REINDEX_BY_VERSION,
            "stored collation version differs from current operating-system version",
        )
    if scanDecision == VERDICT_UNKNOWN:
        return (VERDICT_UNKNOWN, "collation version state is unknown")
    if amcheckStatus is None:
        return (VERDICT_UNKNOWN, "amcheck result is missing")
    if amcheckStatus == AMCHECK_OK:
        return (VERDICT_OK, "collation versions match and amcheck passed")
    if amcheckStatus == AMCHECK_TIMEOUT:
        return (VERDICT_UNKNOWN, "amcheck timed out or could not acquire a lock")
    return (VERDICT_UNKNOWN, f"amcheck status is {amcheckStatus}")
