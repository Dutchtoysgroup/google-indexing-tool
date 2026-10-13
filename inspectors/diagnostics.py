"""Interpret observed URL Inspection data without making indexing promises."""


def diagnose(url: str, result: dict) -> dict:
    verdict = result.get("verdict")
    indexed_status = "indexed" if verdict == "PASS" else "not_indexed" if verdict in {"FAIL", "NEUTRAL"} else "unknown"
    indexing_state = result.get("indexing_state")
    noindex = True if indexing_state in {"BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER"} else False if indexing_state == "INDEXING_ALLOWED" else None
    google = result.get("google_canonical")
    declared = result.get("user_canonical")
    return {
        "indexed_status": indexed_status,
        "noindex": noindex,
        "robots_blocked": True if result.get("robots_txt_state") == "DISALLOWED" else False if result.get("robots_txt_state") == "ALLOWED" else None,
        "canonical_mismatch": google != declared if google and declared else None,
        "google_canonical_is_other_url": google != url if google else None,
        "declared_canonical_is_other_url": declared != url if declared else None,
    }
