#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""CoolProp property lookup and a single-fluid vapor-compression cycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openbuild_tools.bom import write_bom
from openbuild_tools.validate import MISSING_COOLPROP

_BAR_TO_PA = 1e5


def load_coolprop() -> Any:
    """Import CoolProp. Tests replace this when the native library is absent."""
    import CoolProp.CoolProp as coolprop
    return coolprop


def fluid_properties(arguments: dict[str, Any]) -> str:
    """Return phase and thermodynamic properties for one or more state points."""
    fluid = _required_text(arguments, "fluid")
    queries = arguments.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries must be a non-empty list")
    try:
        coolprop = load_coolprop()
    except ImportError:
        return MISSING_COOLPROP

    lines: list[str] = []
    for query in queries:
        if not isinstance(query, dict):
            raise ValueError("each query must be an object")
        lines.append(_query_line(coolprop, fluid, query))
    return "\n".join(lines)


def refrigeration_cycle(workspace: Path, arguments: dict[str, Any]) -> str:
    """Solve a four-point cycle, then write cycle.json and the main BOM rows."""
    fluid = _required_text(arguments, "fluid")
    mode = _required_text(arguments, "mode")
    if mode not in ("cooling", "heating"):
        raise ValueError("mode must be cooling or heating")
    evaporator_c = _required_number(arguments, "evaporator_C")
    condenser_c = _required_number(arguments, "condenser_C")
    if condenser_c <= evaporator_c:
        raise ValueError("condenser_C must be above evaporator_C")
    capacity_w = _required_number(arguments, "capacity_W")
    if capacity_w <= 0:
        raise ValueError("capacity_W must be positive")
    superheat_k = _optional_number(arguments, "superheat_K", 0.0)
    subcooling_k = _optional_number(arguments, "subcooling_K", 0.0)
    efficiency = _optional_number(arguments, "isentropic_efficiency", 0.7)
    if superheat_k < 0 or subcooling_k < 0:
        raise ValueError("superheat_K and subcooling_K must be zero or positive")
    if efficiency <= 0 or efficiency > 1:
        raise ValueError("isentropic_efficiency must be between 0 and 1")

    try:
        coolprop = load_coolprop()
    except ImportError:
        return MISSING_COOLPROP

    evaporator_k = evaporator_c + 273.15
    condenser_k = condenser_c + 273.15
    evaporator_pressure = _si(coolprop, "P", "T", evaporator_k, "Q", 1.0, fluid)
    condenser_pressure = _si(coolprop, "P", "T", condenser_k, "Q", 0.0, fluid)
    suction_temperature = evaporator_k + superheat_k
    suction_enthalpy = _si(coolprop, "H", "T", suction_temperature, "P", evaporator_pressure, fluid)
    suction_entropy = _si(coolprop, "S", "T", suction_temperature, "P", evaporator_pressure, fluid)
    isentropic_enthalpy = _si(coolprop, "H", "P", condenser_pressure, "S", suction_entropy, fluid)
    discharge_enthalpy = suction_enthalpy + (isentropic_enthalpy - suction_enthalpy) / efficiency
    liquid_temperature = condenser_k - subcooling_k
    liquid_enthalpy = _si(coolprop, "H", "T", liquid_temperature, "P", condenser_pressure, fluid)

    evaporator_duty = suction_enthalpy - liquid_enthalpy
    compressor_work = discharge_enthalpy - suction_enthalpy
    condenser_duty = discharge_enthalpy - liquid_enthalpy
    if evaporator_duty <= 0 or compressor_work <= 0 or condenser_duty <= 0:
        raise ValueError("cycle enthalpies are not physical")

    if mode == "cooling":
        mass_flow = capacity_w / evaporator_duty
        cooling_capacity = capacity_w
        heating_capacity = mass_flow * condenser_duty
        cop = evaporator_duty / compressor_work
    else:
        mass_flow = capacity_w / condenser_duty
        heating_capacity = capacity_w
        cooling_capacity = mass_flow * evaporator_duty
        cop = condenser_duty / compressor_work
    compressor_power = mass_flow * compressor_work

    payload = {
        "fluid": fluid,
        "mode": mode,
        "evaporator_C": _json_number(evaporator_c),
        "condenser_C": _json_number(condenser_c),
        "superheat_K": _json_number(superheat_k),
        "subcooling_K": _json_number(subcooling_k),
        "isentropic_efficiency": _json_number(efficiency),
        "capacity_W": _json_number(capacity_w),
        "capacity_kW": _json_number(capacity_w / 1000.0),
        "cooling_capacity_W": _json_number(cooling_capacity),
        "heating_capacity_W": _json_number(heating_capacity),
        "compressor_power_W": _json_number(compressor_power),
        "cop": _json_number(cop),
        "mass_flow_kg_s": _json_number(mass_flow),
        "evaporator_pressure_bar": _json_number(evaporator_pressure / _BAR_TO_PA),
        "condenser_pressure_bar": _json_number(condenser_pressure / _BAR_TO_PA),
    }
    (workspace / "cycle.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    bom_result = write_bom(workspace, [
        {
            "partNumber": "COMP",
            "description": f"Compressor, {_watts(compressor_power)}",
            "quantity": 1,
        },
        {
            "partNumber": "EVAP",
            "description": f"Evaporator, {_watts(cooling_capacity)}",
            "quantity": 1,
        },
        {
            "partNumber": "COND",
            "description": f"Condenser, {_watts(heating_capacity)}",
            "quantity": 1,
        },
    ])
    return (
        f"{mode} {fluid}: COP {_round(cop)}, compressor {_watts(compressor_power)}, "
        f"evaporator {_watts(cooling_capacity)}, condenser {_watts(heating_capacity)}, "
        f"mass flow {_round(mass_flow)} kg/s\n"
        f"wrote cycle.json\n{bom_result}"
    )


def _query_line(coolprop: Any, fluid: str, query: dict[str, Any]) -> str:
    name = query.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("query name is required")
    quality = query.get("quality")
    if quality is not None:
        if isinstance(quality, bool) or not isinstance(quality, (int, float)) or not 0 <= float(quality) <= 1:
            raise ValueError("quality must be a number from 0 to 1")
        if "temperature_C" not in query:
            raise ValueError("temperature_C is required when quality is set")
        temperature_c = _as_number(query["temperature_C"], "temperature_C")
        temperature_k = temperature_c + 273.15
        pressure = _si(coolprop, "P", "T", temperature_k, "Q", float(quality), fluid)
        density = _si(coolprop, "D", "T", temperature_k, "Q", float(quality), fluid)
        enthalpy = _si(coolprop, "H", "T", temperature_k, "Q", float(quality), fluid)
        entropy = _si(coolprop, "S", "T", temperature_k, "Q", float(quality), fluid)
        phase = str(coolprop.PhaseSI("T", temperature_k, "Q", float(quality), fluid))
    else:
        if "temperature_C" not in query or "pressure_bar" not in query:
            raise ValueError("temperature_C and pressure_bar are required when quality is omitted")
        temperature_c = _as_number(query["temperature_C"], "temperature_C")
        pressure_bar = _as_number(query["pressure_bar"], "pressure_bar")
        temperature_k = temperature_c + 273.15
        pressure = pressure_bar * _BAR_TO_PA
        density = _si(coolprop, "D", "T", temperature_k, "P", pressure, fluid)
        enthalpy = _si(coolprop, "H", "T", temperature_k, "P", pressure, fluid)
        entropy = _si(coolprop, "S", "T", temperature_k, "P", pressure, fluid)
        phase = str(coolprop.PhaseSI("T", temperature_k, "P", pressure, fluid))
    return (
        f"{name}: T={_json_number(temperature_c)} C, P={_json_number(pressure / _BAR_TO_PA)} bar, "
        f"phase={phase}, density={_json_number(density)} kg/m3, "
        f"enthalpy={_json_number(enthalpy / 1000.0)} kJ/kg, entropy={_json_number(entropy / 1000.0)} kJ/kg-K"
    )


def _si(coolprop: Any, output: str, first: str, first_value: float, second: str, second_value: float, fluid: str) -> float:
    return float(coolprop.PropsSI(output, first, first_value, second, second_value, fluid))


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _required_number(arguments: dict[str, Any], key: str) -> float:
    if key not in arguments:
        raise ValueError(f"{key} is required")
    return _as_number(arguments[key], key)


def _optional_number(arguments: dict[str, Any], key: str, default: float) -> float:
    if key not in arguments or arguments[key] is None:
        return default
    return _as_number(arguments[key], key)


def _as_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _json_number(value: float) -> int | float:
    rounded = round(value, 6)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _round(value: float) -> str:
    return f"{_json_number(value)}"


def _watts(value: float) -> str:
    return f"{value:.0f} W"
