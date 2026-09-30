#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""Check system.yaml constraints, including the envelope and fluid state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openbuild_tools.geometry import RESULT_PATH

MISSING_COOLPROP = "CoolProp is not installed. Install CoolProp to run fluid checks."
_BAR_TO_PA = 1e5


def validate(workspace: Path) -> str:
    """Compare the last bounding box and configured fluid checks with system.yaml."""
    try:
        return _validate(workspace)
    except (ValueError, RuntimeError) as error:
        return f"failed\n{error}"


def _validate(workspace: Path) -> str:
    document = _load_system(workspace / "system.yaml")
    envelope = _envelope(document)
    checks = _check_entries(document.get("checks"))
    lines: list[str] = []
    failed = False

    if envelope is None:
        lines.append("no envelope constraint")
    else:
        envelope_line, envelope_failed = _check_envelope(workspace, envelope)
        lines.append(envelope_line)
        failed = envelope_failed

    for entry in checks:
        name = entry if isinstance(entry, str) else str(entry.get("name"))
        if name == "envelope":
            continue
        if name == "fluid_state" and isinstance(entry, dict):
            fluid_line, fluid_failed = _check_fluid_state(entry)
            lines.append(fluid_line)
            failed = failed or fluid_failed
            continue
        failed = True
        lines.append(f"{name}: not implemented")

    status = "failed" if failed else "ok"
    return status + "\n" + "\n".join(lines)


def _check_envelope(workspace: Path, envelope: dict[str, int | float]) -> tuple[str, bool]:
    result_path = workspace / RESULT_PATH
    if not result_path.is_file():
        return "no compile result at geometry/.openbuild-result.json", True
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"geometry/.openbuild-result.json is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("geometry/.openbuild-result.json must be an object")
    if not payload.get("ok"):
        return "last compile failed", True
    bbox = _bbox(payload.get("bbox"))
    if bbox is None:
        return "compile result has no bounding box", True

    exceeded = [axis for axis in ("x", "y", "z") if bbox[axis] > envelope[axis]]
    actual = _format_size(bbox)
    limit = _format_size(envelope)
    if exceeded:
        axes = ", ".join(exceeded)
        return f"envelope: size {actual} mm exceeds {limit} mm on {axes}", True
    return f"envelope: {actual} mm fits {limit} mm", False


def _load_system(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError("system.yaml is missing")
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is not installed. Install the Open Build Python requirements.") from error
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("system.yaml must be a mapping")
    return loaded


def _envelope(document: dict[str, Any]) -> dict[str, int | float] | None:
    constraints = document.get("constraints")
    if constraints is None:
        return None
    if not isinstance(constraints, dict):
        raise ValueError("constraints must be a mapping")
    envelope = constraints.get("envelope_mm")
    if envelope is None:
        return None
    if not isinstance(envelope, dict):
        raise ValueError("constraints.envelope_mm must be a mapping")
    size: dict[str, int | float] = {}
    for axis in ("x", "y", "z"):
        if axis not in envelope:
            raise ValueError(f"constraints.envelope_mm.{axis} is required")
        value = envelope[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"constraints.envelope_mm.{axis} must be a number")
        size[axis] = _json_number(float(value))
    return size


def load_coolprop() -> Any:
    """Import CoolProp. Tests replace this when the native library is absent."""
    import CoolProp.CoolProp as coolprop
    return coolprop


def _check_entries(checks: object) -> list[str | dict[str, Any]]:
    if checks is None:
        return []
    if not isinstance(checks, list):
        raise ValueError("checks must be a list")
    entries: list[str | dict[str, Any]] = []
    for item in checks:
        if isinstance(item, str):
            entries.append(item)
            continue
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            entries.append(item)
            continue
        raise ValueError("each check must be a name or an object with a name")
    return entries


def _check_fluid_state(spec: dict[str, Any]) -> tuple[str, bool]:
    fluid = spec.get("fluid")
    if not isinstance(fluid, str) or not fluid.strip():
        raise ValueError("fluid_state.fluid is required")
    temperature_c = _required_number(spec, "temperature_C")
    pressure_bar = _required_number(spec, "pressure_bar")
    expect_phase = spec.get("expect_phase")
    if expect_phase is not None and not isinstance(expect_phase, str):
        raise ValueError("fluid_state.expect_phase must be a string")
    minimum = _optional_number(spec, "min_density_kg_m3")
    maximum = _optional_number(spec, "max_density_kg_m3")

    try:
        coolprop = load_coolprop()
    except ImportError:
        return f"fluid_state: {MISSING_COOLPROP}", True

    temperature_k = temperature_c + 273.15
    pressure_pa = pressure_bar * _BAR_TO_PA
    phase = str(coolprop.PhaseSI("T", temperature_k, "P", pressure_pa, fluid))
    density = float(coolprop.PropsSI("D", "T", temperature_k, "P", pressure_pa, fluid))
    summary = (
        f"fluid_state: {fluid} at {_json_number(temperature_c)} C and {_json_number(pressure_bar)} bar "
        f"is {phase}, density {_json_number(density)} kg/m3"
    )
    problems: list[str] = []
    if isinstance(expect_phase, str) and phase.lower() != expect_phase.strip().lower():
        problems.append(f"expected {expect_phase.strip()}")
    if minimum is not None and density < minimum:
        problems.append(f"density below min {_json_number(minimum)} kg/m3")
    if maximum is not None and density > maximum:
        problems.append(f"density above max {_json_number(maximum)} kg/m3")
    if problems:
        return f"{summary}; {'; '.join(problems)}", True
    return summary, False


def _required_number(spec: dict[str, Any], key: str) -> float:
    if key not in spec:
        raise ValueError(f"fluid_state.{key} is required")
    return _as_number(spec[key], f"fluid_state.{key}")


def _optional_number(spec: dict[str, Any], key: str) -> float | None:
    if key not in spec or spec[key] is None:
        return None
    return _as_number(spec[key], f"fluid_state.{key}")


def _as_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _bbox(value: object) -> dict[str, int | float] | None:
    if not isinstance(value, dict):
        return None
    size: dict[str, int | float] = {}
    for axis in ("x", "y", "z"):
        component = value.get(axis)
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            return None
        size[axis] = _json_number(float(component))
    return size


def _format_size(size: dict[str, int | float]) -> str:
    return f"{size['x']} x {size['y']} x {size['z']}"


def _json_number(value: float) -> int | float:
    if value == int(value):
        return int(value)
    return value
