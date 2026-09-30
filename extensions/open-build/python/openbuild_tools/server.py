#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
"""stdio MCP server that exposes the Open Build engineering tools."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from openbuild_tools.bom import write_bom
from openbuild_tools.catalog import import_datasheet, search_catalog, write_catalog
from openbuild_tools.fluids import fluid_properties, refrigeration_cycle
from openbuild_tools.geometry import compile_geometry, export_step
from openbuild_tools.paths import workspace_from_env
from openbuild_tools.validate import validate

_SCRIPT = {
    "type": "string",
    "description": "Workspace-relative path to a Python file that defines build().",
}
_OBJECT = "object"

TOOLS: list[types.Tool] = [
    types.Tool(
        name="compile_geometry",
        description="Load a workspace Python file, call build(), and record a bounding box. Failures return the traceback.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "required": ["script"],
            "properties": {"script": _SCRIPT},
        },
    ),
    types.Tool(
        name="export_step",
        description="Call build() and write a STEP file inside the workspace. Requires build123d.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "required": ["script", "output"],
            "properties": {
                "script": _SCRIPT,
                "output": {
                    "type": "string",
                    "description": "Workspace-relative path of the STEP file to write.",
                },
            },
        },
    ),
    types.Tool(
        name="validate",
        description="Read system.yaml and compare the last compile_geometry bounding box with constraints.envelope_mm. A fluid_state check calls CoolProp for phase and density. Other check names are reported as not implemented.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "properties": {},
        },
    ),
    types.Tool(
        name="fluid_properties",
        description="Look up CoolProp properties for named refrigerant state points. Each query uses quality at a Celsius temperature, or both temperature_C and pressure_bar. Returns pressure, density, enthalpy, entropy, and phase.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "required": ["fluid", "queries"],
            "properties": {
                "fluid": {"type": "string", "description": "CoolProp fluid name, for example R290 or Water."},
                "queries": {
                    "type": "array",
                    "items": {
                        "type": _OBJECT,
                        "additionalProperties": False,
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string"},
                            "temperature_C": {"type": "number"},
                            "pressure_bar": {"type": "number"},
                            "quality": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                    },
                },
            },
        },
    ),
    types.Tool(
        name="refrigeration_cycle",
        description="Solve a single-fluid vapor-compression cycle. capacity_W is evaporator duty in cooling mode and condenser duty in heating mode. Writes cycle.json and COMP, EVAP, and COND rows in bom.json.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "required": ["fluid", "evaporator_C", "condenser_C", "mode", "capacity_W"],
            "properties": {
                "fluid": {"type": "string"},
                "evaporator_C": {"type": "number"},
                "condenser_C": {"type": "number"},
                "superheat_K": {"type": "number"},
                "subcooling_K": {"type": "number"},
                "isentropic_efficiency": {"type": "number"},
                "mode": {"type": "string", "enum": ["cooling", "heating"]},
                "capacity_W": {"type": "number"},
            },
        },
    ),
    types.Tool(
        name="import_datasheet",
        description="Save a supplier PDF from a url or a workspace path into catalog/sources and return its text. Does not write catalog rows.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "properties": {
                "url": {"type": "string", "description": "http or https URL of a PDF datasheet."},
                "path": {"type": "string", "description": "Workspace-relative path of a PDF already in the project."},
            },
        },
    ),
    types.Tool(
        name="write_catalog",
        description="Merge component rows into catalog/components.json by partNumber. One model with several published duties is one row with several ratings.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": _OBJECT,
                        "additionalProperties": False,
                        "required": ["partNumber", "manufacturer", "category", "description"],
                        "properties": {
                            "partNumber": {"type": "string"},
                            "manufacturer": {"type": "string"},
                            "category": {"type": "string"},
                            "description": {"type": "string"},
                            "refrigerants": {"type": "array", "items": {"type": "string"}},
                            "displacement_m3_h": {"type": "number"},
                            "weight_kg": {"type": "number"},
                            "envelope_mm": {
                                "type": _OBJECT,
                                "additionalProperties": False,
                                "required": ["x", "y", "z"],
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                    "z": {"type": "number"},
                                },
                            },
                            "ratings": {
                                "type": "array",
                                "items": {
                                    "type": _OBJECT,
                                    "additionalProperties": False,
                                    "required": ["fluid", "evaporator_C", "condenser_C", "capacity_W"],
                                    "properties": {
                                        "fluid": {"type": "string"},
                                        "evaporator_C": {"type": "number"},
                                        "condenser_C": {"type": "number"},
                                        "capacity_W": {"type": "number"},
                                    },
                                },
                            },
                            "source": {
                                "type": _OBJECT,
                                "additionalProperties": False,
                                "properties": {
                                    "file": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
    ),
    types.Tool(
        name="search_catalog",
        description="Find catalog components. A capacity filter matches only a published rating at the same refrigerant, evaporator_C, and condenser_C. It does not interpolate.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "properties": {
                "category": {"type": "string"},
                "refrigerant": {"type": "string"},
                "evaporator_C": {"type": "number"},
                "condenser_C": {"type": "number"},
                "min_capacity_W": {"type": "number"},
            },
        },
    ),
    types.Tool(
        name="write_bom",
        description="Merge component rows into the workspace bom.json by partNumber.",
        input_schema={
            "type": _OBJECT,
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": _OBJECT,
                        "additionalProperties": False,
                        "required": ["partNumber", "description", "quantity"],
                        "properties": {
                            "partNumber": {"type": "string"},
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "vendor": {"type": "string"},
                        },
                    },
                },
            },
        },
    ),
]

_HANDLERS: dict[str, Callable[[Path, dict[str, Any]], str]] = {
    "compile_geometry": lambda workspace, arguments: compile_geometry(workspace, _required_string(arguments, "script")),
    "export_step": lambda workspace, arguments: export_step(
        workspace,
        _required_string(arguments, "script"),
        _required_string(arguments, "output"),
    ),
    "validate": lambda workspace, _arguments: validate(workspace),
    "fluid_properties": lambda _workspace, arguments: fluid_properties(arguments),
    "refrigeration_cycle": lambda workspace, arguments: refrigeration_cycle(workspace, arguments),
    "import_datasheet": lambda workspace, arguments: import_datasheet(workspace, arguments),
    "write_catalog": lambda workspace, arguments: write_catalog(workspace, arguments.get("items")),
    "search_catalog": lambda workspace, arguments: search_catalog(workspace, arguments),
    "write_bom": lambda workspace, arguments: write_bom(workspace, arguments.get("items")),
}


class _ArgumentError(Exception):
    pass


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _ArgumentError(f"{key} is required")
    return value


async def _list_tools(_context: object, _params: object) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def _call_tool(_context: object, params: types.CallToolRequestParams) -> types.CallToolResult:
    arguments = params.arguments or {}
    handler = _HANDLERS.get(params.name)
    if handler is None:
        text = f"unknown tool: {params.name}"
    else:
        text = _invoke(handler, arguments)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def _invoke(handler: Callable[[Path, dict[str, Any]], str], arguments: dict[str, Any]) -> str:
    try:
        workspace = workspace_from_env()
        return handler(workspace, arguments)
    except _ArgumentError as error:
        return str(error)
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def _server() -> Server:
    return Server(
        "open-build",
        version="1.0.0",
        instructions="Open Build sizes refrigeration equipment with CoolProp, writes cycle.json, and compiles geometry through build(). Import a supplier datasheet, write one catalog row per component, and search the catalog before choosing equipment. Geometry scripts must define build().",
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    server = _server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
