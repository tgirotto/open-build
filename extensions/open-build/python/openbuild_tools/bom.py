#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""Merge component rows into the workspace bill of materials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_bom(workspace: Path, items: object) -> str:
    """Merge items into bom.json by partNumber. Existing rows are updated in place."""
    if not isinstance(items, list):
        return "items must be a list"
    try:
        incoming = [_normalize_item(item) for item in items]
    except ValueError as error:
        return str(error)

    bom_path = workspace / "bom.json"
    existing = _read_bom(bom_path)
    if isinstance(existing, str):
        return existing

    index: dict[str, int] = {}
    for position, item in enumerate(existing):
        part_number = item.get("partNumber")
        if isinstance(part_number, str) and part_number not in index:
            index[part_number] = position

    for item in incoming:
        part_number = item["partNumber"]
        if part_number in index:
            merged = dict(existing[index[part_number]])
            merged.update(item)
            existing[index[part_number]] = merged
        else:
            index[part_number] = len(existing)
            existing.append(item)

    bom_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return f"wrote {len(existing)} items to bom.json"


def _read_bom(path: Path) -> list[dict[str, Any]] | str:
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return f"bom.json is not valid JSON: {error}"
    if not isinstance(loaded, list):
        return "bom.json must be a JSON array"
    if any(not isinstance(item, dict) for item in loaded):
        return "bom.json must be an array of objects"
    return loaded


def _normalize_item(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("BOM item must be an object")
    part_number = item.get("partNumber")
    description = item.get("description")
    quantity = item.get("quantity")
    if not isinstance(part_number, str) or not part_number.strip():
        raise ValueError("BOM item partNumber is required")
    if not isinstance(description, str):
        raise ValueError("BOM item description is required")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
        raise ValueError("BOM item quantity is required")
    normalized: dict[str, Any] = {
        "partNumber": part_number,
        "description": description,
        "quantity": quantity,
    }
    if "vendor" in item and item["vendor"] is not None:
        vendor = item["vendor"]
        if not isinstance(vendor, str):
            raise ValueError("BOM item vendor must be a string")
        normalized["vendor"] = vendor
    return normalized
