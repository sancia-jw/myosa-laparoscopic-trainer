"""Extract V2 raw metrics from firmware FINAL_SCORE rows."""

from __future__ import annotations

import math
from typing import Any


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _apply_transform(value: float | None, transform: str | None) -> float | None:
    if value is None:
        return None
    if transform == "ms_to_s":
        return value / 1000.0
    return value


def extract_raw_metrics(
    final_row: dict[str, Any],
    metric_defs: list[dict[str, Any]],
) -> tuple[dict[str, float | None], list[str]]:
    """Return raw metric values and warnings for missing optional fields."""
    raw: dict[str, float | None] = {}
    warnings: list[str] = []

    for spec in metric_defs:
        name = str(spec["name"])
        field = str(spec.get("final_score_field", name))
        value = _safe_float(final_row.get(field))
        value = _apply_transform(value, spec.get("transform"))
        if value is not None:
            vmin = float(spec.get("valid_min", -math.inf))
            vmax = float(spec.get("valid_max", math.inf))
            value = max(vmin, min(vmax, value))
        raw[name] = value
        if value is None:
            if spec.get("optional"):
                warnings.append(f"{name}: optional field '{field}' missing from telemetry")
            else:
                warnings.append(f"{name}: required field '{field}' missing or invalid")

    return raw, warnings
