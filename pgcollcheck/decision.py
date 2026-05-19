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


def classify_collation_version(
    stored_version: str | None,
    actual_version: str | None,
) -> str:
    from .models import (
        SCAN_OK,
        SCAN_OK_UNVERSIONED,
    )

    if stored_version is None and actual_version is None:
        return SCAN_OK_UNVERSIONED
    if stored_version is None:
        return SCAN_UNKNOWN_NO_STORED_VERSION
    if actual_version is None:
        return SCAN_UNKNOWN_NO_ACTUAL_VERSION
    if stored_version != actual_version:
        return SCAN_VERSION_MISMATCH
    return SCAN_OK


def decide_scan_result(statuses: list[str]) -> str:
    if SCAN_VERSION_MISMATCH in statuses:
        return VERDICT_REINDEX_BY_VERSION
    if SCAN_UNKNOWN_NO_STORED_VERSION in statuses:
        return VERDICT_UNKNOWN
    if SCAN_UNKNOWN_NO_ACTUAL_VERSION in statuses:
        return VERDICT_UNKNOWN
    return VERDICT_OK


def decide_compare_result(scan_decision: str, amcheck_status: str | None) -> tuple[str, str]:
    version_changed = scan_decision == VERDICT_REINDEX_BY_VERSION
    amcheck_failed = amcheck_status == AMCHECK_FAILED

    if version_changed and amcheck_failed:
        return (
            VERDICT_REINDEX_BY_BOTH,
            "collation version changed and amcheck reported a B-tree problem",
        )
    if amcheck_failed:
        return (
            VERDICT_REINDEX_BY_AMCHECK,
            "amcheck reported a B-tree problem; cause may be collation or another index issue",
        )
    if version_changed:
        return (
            VERDICT_REINDEX_BY_VERSION,
            "stored collation version differs from current operating-system version",
        )
    if scan_decision == VERDICT_UNKNOWN:
        return (VERDICT_UNKNOWN, "collation version state is unknown")
    if amcheck_status is None:
        return (VERDICT_UNKNOWN, "amcheck result is missing")
    if amcheck_status == AMCHECK_OK:
        return (VERDICT_OK, "collation versions match and amcheck passed")
    if amcheck_status == AMCHECK_TIMEOUT:
        return (VERDICT_UNKNOWN, "amcheck timed out or could not acquire a lock")
    return (VERDICT_UNKNOWN, f"amcheck status is {amcheck_status}")
