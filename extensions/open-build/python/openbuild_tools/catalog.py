#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""Save supplier datasheets and merge the catalog rows the agent builds from them."""

from __future__ import annotations

import io
import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from openbuild_tools.paths import WorkspacePathError, relative_path, resolve_workspace_path

_MAX_PDF_BYTES = 20 * 1024 * 1024
_SOURCES = Path("catalog") / "sources"
_COMPONENTS = Path("catalog") / "components.json"
_REQUIRED_TEXT = ("partNumber", "manufacturer", "category", "description")


def download_pdf(url: str) -> bytes:
    """Download a datasheet. Tests replace this so the suite stays offline."""
    request = urllib.request.Request(url, headers={"User-Agent": "OpenBuild/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > _MAX_PDF_BYTES:
                raise ValueError("PDF exceeds the size limit")
            data = response.read(_MAX_PDF_BYTES + 1)
    except urllib.error.URLError as error:
        raise ValueError(f"could not download datasheet: {error.reason}") from error
    if len(data) > _MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the size limit")
    return data


def extract_text(data: bytes) -> str:
    """Return the text layer of a PDF. Tests replace this when pypdf is absent."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def import_datasheet(workspace: Path, arguments: dict[str, Any]) -> str:
    """Save a URL or workspace PDF under catalog/sources and return its text."""
    url = arguments.get("url")
    path = arguments.get("path")
    if url is None and path is None:
        raise ValueError("url or path is required")
    if url is not None and path is not None:
        raise ValueError("provide either url or path")

    if url is not None:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url is required")
        cleaned = url.strip()
        try:
            _require_http(cleaned)
        except ValueError as error:
            return f"rejected: {error}"
        data = download_pdf(cleaned)
        destination = _source_destination(workspace, _source_name(cleaned))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    else:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path is required")
        try:
            source = resolve_workspace_path(workspace, path.strip())
        except WorkspacePathError as error:
            return f"rejected: {error}"
        if not source.is_file():
            return f"file not found: {relative_path(workspace, source)}"
        destination = source if _is_source(workspace, source) else _source_destination(workspace, source.name)
        if destination != source:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        data = destination.read_bytes()

    try:
        text = extract_text(data)
    except ImportError:
        return "pypdf is not installed. Install pypdf to read datasheets."
    saved = relative_path(workspace, destination)
    if not text:
        return f"saved {saved}\nThe PDF has no text layer."
    return f"saved {saved}\n{text}"


def write_catalog(workspace: Path, items: object) -> str:
    """Merge component rows into catalog/components.json by partNumber."""
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")
    incoming = [_normalize_component(item) for item in items]
    catalog_path = workspace / _COMPONENTS
    existing = _read_components(catalog_path)
    index = {
        item["partNumber"]: position
        for position, item in enumerate(existing)
        if isinstance(item.get("partNumber"), str)
    }
    for item in incoming:
        part_number = item["partNumber"]
        if part_number in index:
            merged = dict(existing[index[part_number]])
            merged.update(item)
            existing[index[part_number]] = merged
        else:
            index[part_number] = len(existing)
            existing.append(item)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return f"wrote {len(existing)} items to catalog/components.json"


def search_catalog(workspace: Path, arguments: dict[str, Any]) -> str:
    """Return catalog rows whose published ratings match the requested point."""
    category = _optional_text(arguments, "category")
    refrigerant = _optional_text(arguments, "refrigerant")
    min_capacity = arguments.get("min_capacity_W")
    evaporator = arguments.get("evaporator_C")
    condenser = arguments.get("condenser_C")
    if min_capacity is not None:
        min_capacity = _as_number(min_capacity, "min_capacity_W")
        if min_capacity <= 0:
            raise ValueError("min_capacity_W must be positive")
        if refrigerant is None or evaporator is None or condenser is None:
            raise ValueError("refrigerant, evaporator_C, and condenser_C are required with min_capacity_W")
    evaporator_c = None if evaporator is None else _as_number(evaporator, "evaporator_C")
    condenser_c = None if condenser is None else _as_number(condenser, "condenser_C")

    matches: list[dict[str, Any]] = []
    for item in _read_components(workspace / _COMPONENTS):
        if category is not None and str(item.get("category", "")).lower() != category.lower():
            continue
        if not _component_matches(item, refrigerant, evaporator_c, condenser_c, min_capacity):
            continue
        matches.append(item)
    if not matches:
        return "no catalog components match"
    return "\n".join(_component_line(item) for item in matches)


def _require_http(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("url must be http or https")


def _source_name(url: str) -> str:
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned or 'datasheet'}.pdf"
    return cleaned


def _source_destination(workspace: Path, name: str) -> Path:
    return workspace / _SOURCES / name


def _is_source(workspace: Path, path: Path) -> bool:
    sources = (workspace / _SOURCES).resolve()
    resolved = path.resolve()
    return resolved == sources or sources in resolved.parents


def _read_components(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"catalog/components.json is not valid JSON: {error}") from error
    if not isinstance(loaded, list) or any(not isinstance(item, dict) for item in loaded):
        raise ValueError("catalog/components.json must be an array of objects")
    return loaded


def _normalize_component(item: object) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("catalog item must be an object")
    normalized: dict[str, Any] = {}
    for key in _REQUIRED_TEXT:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"catalog item {key} is required")
        normalized[key] = value.strip()
    if "refrigerants" in item and item["refrigerants"] is not None:
        normalized["refrigerants"] = _text_list(item["refrigerants"], "refrigerants")
    if "ratings" in item and item["ratings"] is not None:
        normalized["ratings"] = _ratings(item["ratings"])
    if "displacement_m3_h" in item and item["displacement_m3_h"] is not None:
        normalized["displacement_m3_h"] = _as_number(item["displacement_m3_h"], "displacement_m3_h")
    if "weight_kg" in item and item["weight_kg"] is not None:
        normalized["weight_kg"] = _as_number(item["weight_kg"], "weight_kg")
    if "envelope_mm" in item and item["envelope_mm"] is not None:
        normalized["envelope_mm"] = _envelope(item["envelope_mm"])
    if "source" in item and item["source"] is not None:
        normalized["source"] = _source(item["source"])
    return normalized


def _ratings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("ratings must be a list")
    ratings: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("rating must be an object")
        fluid = entry.get("fluid")
        if not isinstance(fluid, str) or not fluid.strip():
            raise ValueError("rating fluid is required")
        rating = {
            "fluid": fluid.strip(),
            "evaporator_C": _as_number(entry.get("evaporator_C"), "evaporator_C"),
            "condenser_C": _as_number(entry.get("condenser_C"), "condenser_C"),
            "capacity_W": _as_number(entry.get("capacity_W"), "capacity_W"),
        }
        if rating["capacity_W"] <= 0:
            raise ValueError("rating capacity_W must be positive")
        ratings.append(rating)
    return ratings


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(entry, str) or not entry.strip() for entry in value):
        raise ValueError(f"{label} must be a list of strings")
    return [entry.strip() for entry in value]


def _envelope(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("envelope_mm must be an object")
    return {axis: _as_number(value.get(axis), f"envelope_mm.{axis}") for axis in ("x", "y", "z")}


def _source(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("source must be an object")
    source: dict[str, str] = {}
    for key in ("file", "url"):
        if key not in value or value[key] is None:
            continue
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"source.{key} must be a string")
        source[key] = value[key].strip()
    return source


def _component_matches(
    item: dict[str, Any],
    refrigerant: str | None,
    evaporator_c: float | None,
    condenser_c: float | None,
    min_capacity: float | None,
) -> bool:
    ratings = item.get("ratings")
    published = ratings if isinstance(ratings, list) else []
    if min_capacity is not None:
        return any(
            _same_text(rating.get("fluid"), refrigerant)
            and _same_number(rating.get("evaporator_C"), evaporator_c)
            and _same_number(rating.get("condenser_C"), condenser_c)
            and isinstance(rating.get("capacity_W"), (int, float))
            and not isinstance(rating.get("capacity_W"), bool)
            and float(rating["capacity_W"]) >= min_capacity
            for rating in published
            if isinstance(rating, dict)
        )
    if refrigerant is None:
        return True
    names = item.get("refrigerants")
    if isinstance(names, list) and any(_same_text(name, refrigerant) for name in names):
        return True
    return any(_same_text(rating.get("fluid"), refrigerant) for rating in published if isinstance(rating, dict))


def _component_line(item: dict[str, Any]) -> str:
    lines = [f"{item.get('partNumber')}: {item.get('manufacturer')} {item.get('category')}"]
    ratings = item.get("ratings")
    if isinstance(ratings, list):
        for rating in ratings:
            if not isinstance(rating, dict):
                continue
            lines.append(
                f"  {rating.get('fluid')} at {_format_number(rating.get('evaporator_C'))}/{_format_number(rating.get('condenser_C'))} C: {_format_number(rating.get('capacity_W'))} W"
            )
    return "\n".join(lines)


def _optional_text(arguments: dict[str, Any], key: str) -> str | None:
    if key not in arguments or arguments[key] is None:
        return None
    value = arguments[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a string")
    return value.strip()


def _format_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    rounded = round(float(value), 6)
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def _as_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _same_text(left: object, right: str | None) -> bool:
    return isinstance(left, str) and right is not None and left.lower() == right.lower()


def _same_number(left: object, right: float | None) -> bool:
    if right is None or isinstance(left, bool) or not isinstance(left, (int, float)):
        return False
    return abs(float(left) - right) <= 1e-6
