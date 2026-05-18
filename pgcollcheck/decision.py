from __future__ import annotations

from .models import (
    SCAN_UNKNOWN_NO_ACTUAL_VERSION,
    SCAN_UNKNOWN_NO_STORED_VERSION,
    SCAN_VERSION_MISMATCH,
    VERDICT_OK,
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
