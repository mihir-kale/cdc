"""Load the generated FinePrint Safety Label artifact for the API.

Deliberately standard-library only. The score itself is produced offline by
``app.safety_labels`` (which does need pandas and scipy); the running service
just reads the JSON that script wrote, so serving a label does not require the
statistics stack to be installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ARTIFACT_PATH = Path(__file__).resolve().parent / "generated" / "lender_safety_labels.json"

_MISSING_ARTIFACT_MESSAGE = (
    "The lender safety label artifact has not been generated. Run "
    "`python -m app.safety_labels` from backend/ to build "
    f"{ARTIFACT_PATH} from data/processed/payday_shrunk_features.csv."
)

_cache: dict[str, Any] | None = None


def load_artifact(path: Path = ARTIFACT_PATH) -> dict[str, Any]:
    """Read and cache the artifact. Raises FileNotFoundError with a fix if absent."""
    global _cache
    if _cache is None:
        if not path.exists():
            raise FileNotFoundError(_MISSING_ARTIFACT_MESSAGE)
        _cache = json.loads(path.read_text(encoding="utf-8"))
    return _cache


def lender_index() -> list[dict[str, Any]]:
    """Lightweight rows for lender search: identity and evidence only."""
    artifact = load_artifact()
    return [
        {
            "id": lender["id"],
            "name": lender["name"],
            "n_complaints": lender["n_complaints"],
            "evidence": lender["evidence"],
        }
        for lender in artifact["lenders"]
    ]


def get_lender(lender_id: str) -> dict[str, Any] | None:
    """Full safety label for one lender, with dimension metadata attached."""
    artifact = load_artifact()
    for lender in artifact["lenders"]:
        if lender["id"] == lender_id:
            record = {
                **lender,
                "method": artifact["method"],
                "methodology": artifact["methodology"],
                "dimensions": {
                    slug: {**artifact["dimensions"][slug], **values}
                    for slug, values in lender["dimensions"].items()
                },
            }
            # The observed issue taxonomy travels with the label, so a consumer
            # surface can name the underlying CFPB issues without rebuilding the
            # mapping and without the raw complaint dataset leaving the backend.
            if "issues" in artifact:
                record["issues"] = artifact["issues"]
                record["complaint_share_note"] = artifact.get("complaint_share_note")
            return record
    return None


def dataset_summary() -> dict[str, Any]:
    """Counts and methodology shown alongside the label."""
    artifact = load_artifact()
    summary = {
        "lender_count": artifact["lender_count"],
        "total_complaints": artifact["total_complaints"],
        "method": artifact["method"],
        "methodology": artifact["methodology"],
        "dimensions": artifact["dimensions"],
    }
    if "issues" in artifact:
        summary["issue_taxonomy_size"] = len(artifact["issues"])
    return summary
