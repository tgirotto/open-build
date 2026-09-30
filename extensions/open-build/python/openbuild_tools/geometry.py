#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""Compile geometry scripts and export STEP files."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from openbuild_tools.paths import WorkspacePathError, relative_path, resolve_workspace_path

RESULT_PATH = Path("geometry") / ".openbuild-result.json"
MISSING_BUILD123D = "build123d is not installed. Install build123d to export STEP files."


def build123d_available() -> bool:
    try:
        import build123d  # noqa: F401
    except ImportError:
        return False
    return True


def compile_geometry(workspace: Path, script: str) -> str:
    """Load a script, call build(), and record the bounding box."""
    try:
        script_path = resolve_workspace_path(workspace, script)
    except WorkspacePathError as error:
        return f"rejected: {error}"

    relative = relative_path(workspace, script_path)
    if not script_path.is_file():
        message = f"script not found: {relative}"
        _write_result(workspace, {"ok": False, "script": relative, "error": message})
        return message

    try:
        result, stdout, stderr = _call_build(script_path)
    except Exception:
        failure = traceback.format_exc()
        _write_result(workspace, {"ok": False, "script": relative, "error": failure})
        return failure

    bbox = bbox_from_result(result)
    _write_result(workspace, {"ok": True, "script": relative, "bbox": bbox})
    stl_path = _try_write_stl(workspace, result)
    return _success_text(stdout, stderr, bbox, stl_path)


def export_step(workspace: Path, script: str, output: str) -> str:
    """Call build() and write a STEP file inside the workspace."""
    try:
        script_path = resolve_workspace_path(workspace, script)
        output_path = resolve_workspace_path(workspace, output)
    except WorkspacePathError as error:
        return f"rejected: {error}"

    if not script_path.is_file():
        return f"script not found: {relative_path(workspace, script_path)}"
    if output_path.is_dir():
        return f"output is a directory: {relative_path(workspace, output_path)}"
    if not build123d_available():
        return MISSING_BUILD123D

    try:
        result, _stdout, _stderr = _call_build(script_path)
        _write_step(result, output_path)
    except Exception:
        return traceback.format_exc()
    return f"wrote {relative_path(workspace, output_path)}"


def bbox_from_result(result: object) -> dict[str, int | float] | None:
    """Read a bounding-box size from a build() result.

    A dict ``{"bbox": {"x", "y", "z"}}`` is accepted so tests and scripts can
    report a size without build123d. build123d shapes expose bounding_box().
    """
    if isinstance(result, dict) and "bbox" in result:
        return _size_from_box(result["bbox"])
    bbox_attr = getattr(result, "bbox", None)
    if bbox_attr is not None and not callable(bbox_attr):
        parsed = _size_from_box(bbox_attr)
        if parsed is not None:
            return parsed
    bounding_box = getattr(result, "bounding_box", None)
    if callable(bounding_box):
        return _size_from_box(bounding_box())
    return None


def _call_build(script_path: Path) -> tuple[object, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    module_name = f"openbuild_user_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script_path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            spec.loader.exec_module(module)
            build = getattr(module, "build", None)
            if not callable(build):
                raise RuntimeError(f"{script_path.name} must define a build() function")
            result = build()
    finally:
        sys.modules.pop(module_name, None)
    return result, stdout.getvalue(), stderr.getvalue()


def _write_step(shape: object, destination: Path) -> None:
    import build123d

    export = getattr(build123d, "export_step", None)
    if not callable(export):
        from build123d.exporters3d import export_step as export
    destination.parent.mkdir(parents=True, exist_ok=True)
    export(shape, destination)


def _write_result(workspace: Path, payload: dict[str, Any]) -> None:
    path = workspace / RESULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _try_write_stl(workspace: Path, result: object) -> str | None:
    """Write geometry/part.stl when build() returns a build123d shape."""
    if isinstance(result, dict) or not callable(getattr(result, "bounding_box", None)):
        return None
    if not build123d_available():
        return None
    destination = workspace / "geometry" / "part.stl"
    try:
        _write_stl(result, destination)
    except Exception:
        return None
    return "geometry/part.stl"


def _write_stl(shape: object, destination: Path) -> None:
    import build123d

    export = getattr(build123d, "export_stl", None)
    if not callable(export):
        from build123d import export_stl as export
    destination.parent.mkdir(parents=True, exist_ok=True)
    export(shape, destination)


def _success_text(stdout: str, stderr: str, bbox: dict[str, int | float] | None, stl_path: str | None = None) -> str:
    parts: list[str] = []
    if stdout.strip():
        parts.append(stdout.rstrip())
    if stderr.strip():
        parts.append(stderr.rstrip())
    if bbox is not None:
        parts.append(f"bounding box mm: x={bbox['x']} y={bbox['y']} z={bbox['z']}")
    if stl_path is not None:
        parts.append(f"wrote {stl_path}")
    if not parts:
        return "ok\n"
    return "\n".join(parts) + "\n"


def _size_from_box(box: object) -> dict[str, int | float] | None:
    if isinstance(box, dict) and "min" in box and "max" in box:
        return _size_from_min_max(box["min"], box["max"])
    size = box.get("size") if isinstance(box, dict) else getattr(box, "size", None)
    if size is not None:
        dims = _xyz(size)
        if dims is not None:
            return _as_json_size(dims)
    min_value = box.get("min") if isinstance(box, dict) else getattr(box, "min", None)
    max_value = box.get("max") if isinstance(box, dict) else getattr(box, "max", None)
    if min_value is not None and max_value is not None:
        parsed = _size_from_min_max(min_value, max_value)
        if parsed is not None:
            return parsed
    dims = _xyz(box)
    if dims is None:
        return None
    return _as_json_size(dims)


def _size_from_min_max(min_value: object, max_value: object) -> dict[str, int | float] | None:
    start = _xyz(min_value)
    end = _xyz(max_value)
    if start is None or end is None:
        return None
    return {axis: _json_number(abs(end[axis] - start[axis])) for axis in ("x", "y", "z")}


def _xyz(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    coords: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        component = _component(value, (axis, axis.upper()))
        if component is None:
            return None
        coords[axis] = component
    return coords


def _component(value: object, names: tuple[str, ...]) -> float | None:
    for name in names:
        if isinstance(value, dict) and name in value:
            raw = value[name]
        elif not isinstance(value, dict) and hasattr(value, name):
            raw = getattr(value, name)
        else:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)
    return None


def _as_json_size(coords: dict[str, float]) -> dict[str, int | float]:
    return {axis: _json_number(coords[axis]) for axis in ("x", "y", "z")}


def _json_number(value: float) -> int | float:
    if value == int(value):
        return int(value)
    return value
