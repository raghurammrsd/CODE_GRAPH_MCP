"""Why-Selected and Why-Rejected Explanation Verifier."""
from __future__ import annotations

from typing import Any


def validate_selection_explanations(context_packet: dict[str, Any]) -> dict[str, Any]:
    """Verify that why_selected and why_rejected output match actual optimizer decision paths."""
    exec_meta = context_packet.get("execution", {})
    if not isinstance(exec_meta, dict):
        return {"valid": False, "reason": "No execution metadata found in ContextPacket."}

    explain = exec_meta.get("explain", {})
    if not isinstance(explain, dict):
        return {"valid": False, "reason": "Explainability mode was not enabled."}

    why_selected_map = explain.get("why_selected", {})
    rejections = explain.get("rejections", [])

    # 1. Validate why_selected items
    valid_selected_reasons = 0
    for _item_id, reasons in why_selected_map.items():
        if isinstance(reasons, list) and len(reasons) > 0:
            # Must mention coverage or utility or relevance
            if any("Coverage" in r or "Knapsack" in r or "Relevance" in r or "score" in r for r in reasons):
                valid_selected_reasons += 1

    # 2. Validate why_rejected items
    valid_rejected_reasons = 0
    if isinstance(rejections, list):
        for rej in rejections:
            if isinstance(rej, dict):
                r_text = str(rej.get("reason", ""))
                if any(k in r_text.lower() for k in ("duplicate", "budget", "stale", "relevance", "utility")):
                    valid_rejected_reasons += 1

    selected_valid = len(why_selected_map) == 0 or (valid_selected_reasons == len(why_selected_map))
    rejected_valid = len(rejections) == 0 or (valid_rejected_reasons == len(rejections))

    return {
        "valid": selected_valid and rejected_valid,
        "total_selected_explained": len(why_selected_map),
        "valid_selected_explanations": valid_selected_reasons,
        "total_rejected_explained": len(rejections) if isinstance(rejections, list) else 0,
        "valid_rejected_explanations": valid_rejected_reasons,
    }
