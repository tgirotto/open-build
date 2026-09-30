#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""Parametric chiller skid sized from cycle.json in the project root."""

import json
from pathlib import Path


def build():
    length, width, height = _size_mm(_capacity_kw())
    try:
        from build123d import Box, Pos
    except ImportError:
        return {"bbox": {"x": length, "y": width, "z": height}}
    frame = Box(length, width, height * 0.1)
    evaporator = Pos(-length * 0.25, 0, height * 0.4) * Box(length * 0.3, width * 0.8, height * 0.5)
    compressor = Pos(0, 0, height * 0.45) * Box(length * 0.2, width * 0.35, height * 0.7)
    condenser = Pos(length * 0.25, 0, height * 0.4) * Box(length * 0.3, width * 0.8, height * 0.55)
    return frame + evaporator + compressor + condenser


def _capacity_kw() -> float:
    path = Path(__file__).resolve().parent.parent / "cycle.json"
    if not path.is_file():
        return 10.0
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return 10.0
    value = loaded.get("capacity_kW", 10.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 10.0
    return float(value)


def _size_mm(capacity_kw: float) -> tuple[float, float, float]:
    scale = max(capacity_kw, 0.1) / 10.0
    return (1200.0 * scale, 600.0 * scale, 500.0 * scale)
