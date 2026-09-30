#---------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License. See License.txt in the project root for license information.
#---------------------------------------------------------------------------------------------
import json
from pathlib import Path

from openbuild_tools.bom import write_bom
from openbuild_tools.catalog import import_datasheet, search_catalog, write_catalog
from openbuild_tools.fluids import fluid_properties, refrigeration_cycle
from openbuild_tools.geometry import MISSING_BUILD123D, compile_geometry, export_step
from openbuild_tools.server import TOOLS
from openbuild_tools.validate import validate


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    message = compile_geometry(tmp_path, "../secret.py")
    assert message.startswith("rejected:")
    assert not (tmp_path.parent / "secret.py").exists()

    absolute = compile_geometry(tmp_path, str(tmp_path.parent / "secret.py"))
    assert absolute.startswith("rejected:")


def test_compile_geometry_returns_traceback(tmp_path: Path) -> None:
    script = tmp_path / "geometry" / "part.py"
    script.parent.mkdir()
    script.write_text("def build():\n    raise RuntimeError('geom failed')\n", encoding="utf-8")

    message = compile_geometry(tmp_path, "geometry/part.py")

    assert "Traceback" in message
    assert "RuntimeError" in message
    assert "geom failed" in message
    payload = json.loads((tmp_path / "geometry" / ".openbuild-result.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["script"] == "geometry/part.py"


def test_validate_fails_when_bbox_exceeds_envelope(tmp_path: Path) -> None:
    geometry = tmp_path / "geometry"
    geometry.mkdir()
    (geometry / "part.py").write_text(
        "def build():\n    return {'bbox': {'x': 2000, 'y': 10, 'z': 10}}\n",
        encoding="utf-8",
    )
    (tmp_path / "system.yaml").write_text(
        "constraints:\n  envelope_mm:\n    x: 1000\n    y: 500\n    z: 400\nchecks:\n  - pressure_drop\n",
        encoding="utf-8",
    )

    compile_geometry(tmp_path, "geometry/part.py")
    result = validate(tmp_path)

    assert result.startswith("failed")
    assert "exceeds" in result
    assert "pressure_drop: not implemented" in result
    payload = json.loads((geometry / ".openbuild-result.json").read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["bbox"] == {"x": 2000, "y": 10, "z": 10}


def _fluid_workspace(tmp_path: Path, check: str) -> None:
    (tmp_path / "system.yaml").write_text(f"checks:\n{check}", encoding="utf-8")


def test_fluid_state_passes_when_phase_matches(tmp_path: Path, monkeypatch) -> None:
    _fluid_workspace(
        tmp_path,
        "  - name: fluid_state\n    fluid: Water\n    temperature_C: 25\n    pressure_bar: 1.01325\n    expect_phase: liquid\n",
    )
    calls: dict[str, tuple] = {}

    class FakeCoolProp:
        def PhaseSI(self, input1, value1, input2, value2, fluid):
            calls["phase"] = (input1, value1, input2, value2, fluid)
            return "liquid"

        def PropsSI(self, output, input1, value1, input2, value2, fluid):
            calls["density"] = (output, input1, value1, input2, value2, fluid)
            return 997.0

    monkeypatch.setattr("openbuild_tools.validate.load_coolprop", lambda: FakeCoolProp())
    result = validate(tmp_path)

    assert result.startswith("ok")
    assert "density 997 kg/m3" in result
    assert calls["phase"] == ("T", 298.15, "P", 101325.0, "Water")
    assert calls["density"][0] == "D"
    assert calls["density"][1:] == ("T", 298.15, "P", 101325.0, "Water")


def test_fluid_state_fails_when_phase_mismatches(tmp_path: Path, monkeypatch) -> None:
    _fluid_workspace(
        tmp_path,
        "  - name: fluid_state\n    fluid: Water\n    temperature_C: 25\n    pressure_bar: 1\n    expect_phase: liquid\n",
    )

    class FakeCoolProp:
        def PhaseSI(self, *_args):
            return "gas"

        def PropsSI(self, *_args):
            return 0.6

    monkeypatch.setattr("openbuild_tools.validate.load_coolprop", lambda: FakeCoolProp())
    result = validate(tmp_path)

    assert result.startswith("failed")
    assert "expected liquid" in result
    assert "density" in result


def test_fluid_state_fails_when_density_exceeds_max(tmp_path: Path, monkeypatch) -> None:
    _fluid_workspace(
        tmp_path,
        "  - name: fluid_state\n    fluid: Water\n    temperature_C: 25\n    pressure_bar: 1\n    max_density_kg_m3: 900\n",
    )

    class FakeCoolProp:
        def PhaseSI(self, *_args):
            return "liquid"

        def PropsSI(self, *_args):
            return 997.0

    monkeypatch.setattr("openbuild_tools.validate.load_coolprop", lambda: FakeCoolProp())
    result = validate(tmp_path)

    assert result.startswith("failed")
    assert "density above max 900 kg/m3" in result


def test_fluid_state_reports_missing_coolprop(tmp_path: Path, monkeypatch) -> None:
    _fluid_workspace(
        tmp_path,
        "  - name: fluid_state\n    fluid: Water\n    temperature_C: 25\n    pressure_bar: 1\n    expect_phase: liquid\n",
    )

    def missing():
        raise ImportError("no coolprop")

    monkeypatch.setattr("openbuild_tools.validate.load_coolprop", missing)
    result = validate(tmp_path)

    assert result.startswith("failed")
    assert "CoolProp is not installed" in result


def test_write_bom_merges_by_part_number(tmp_path: Path) -> None:
    first = write_bom(tmp_path, [{"partNumber": "A", "description": "bolt", "quantity": 1}])
    assert first == "wrote 1 items to bom.json"
    second = write_bom(
        tmp_path,
        [
            {"partNumber": "A", "description": "bolt", "quantity": 4, "vendor": "acme"},
            {"partNumber": "B", "description": "nut", "quantity": 2},
        ],
    )
    assert second == "wrote 2 items to bom.json"
    rows = json.loads((tmp_path / "bom.json").read_text(encoding="utf-8"))
    assert rows == [
        {"partNumber": "A", "description": "bolt", "quantity": 4, "vendor": "acme"},
        {"partNumber": "B", "description": "nut", "quantity": 2},
    ]


def test_export_step_without_build123d(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "geometry" / "part.py"
    script.parent.mkdir()
    script.write_text("def build():\n    return {'bbox': {'x': 1, 'y': 1, 'z': 1}}\n", encoding="utf-8")
    monkeypatch.setattr("openbuild_tools.geometry.build123d_available", lambda: False)

    message = export_step(tmp_path, "geometry/part.py", "out/part.step")

    assert message == MISSING_BUILD123D
    assert not (tmp_path / "out" / "part.step").exists()


def test_fluid_properties_quality_query_converts_celsius(monkeypatch) -> None:
    seen: dict[str, tuple] = {}

    class FakeCoolProp:
        def PropsSI(self, output, first, first_value, second, second_value, fluid):
            seen[output] = (first, first_value, second, second_value, fluid)
            return {"P": 345000.0, "D": 2.0, "H": 580000.0, "S": 2400.0}[output]

        def PhaseSI(self, *_args):
            return "gas"

    monkeypatch.setattr("openbuild_tools.fluids.load_coolprop", lambda: FakeCoolProp())
    text = fluid_properties({
        "fluid": "R290",
        "queries": [{"name": "evaporator_vapor", "temperature_C": -10, "quality": 1}],
    })

    assert "enthalpy=580 kJ/kg" in text
    assert seen["H"][0] == "T"
    assert seen["H"][1] == 263.15
    assert seen["H"][2] == "Q"
    assert seen["H"][3] == 1


def test_refrigeration_cycle_cooling_math(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("openbuild_tools.fluids.load_coolprop", lambda: _CycleCoolProp())
    text = refrigeration_cycle(tmp_path, {
        "fluid": "R290",
        "evaporator_C": -10,
        "condenser_C": 40,
        "superheat_K": 0,
        "subcooling_K": 0,
        "isentropic_efficiency": 0.7,
        "mode": "cooling",
        "capacity_W": 15000,
    })
    payload = json.loads((tmp_path / "cycle.json").read_text(encoding="utf-8"))
    rows = json.loads((tmp_path / "bom.json").read_text(encoding="utf-8"))

    assert "COP 2.1" in text
    assert payload["mass_flow_kg_s"] == 0.1
    assert payload["cop"] == 2.1
    assert payload["compressor_power_W"] == 7142.857143
    assert [row["partNumber"] for row in rows] == ["COMP", "EVAP", "COND"]


def test_refrigeration_cycle_heating_uses_condenser_duty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("openbuild_tools.fluids.load_coolprop", lambda: _CycleCoolProp())
    refrigeration_cycle(tmp_path, {
        "fluid": "R290",
        "evaporator_C": -10,
        "condenser_C": 40,
        "superheat_K": 0,
        "subcooling_K": 0,
        "isentropic_efficiency": 0.7,
        "mode": "heating",
        "capacity_W": _CONDENSER_DUTY,
    })
    payload = json.loads((tmp_path / "cycle.json").read_text(encoding="utf-8"))

    assert payload["mass_flow_kg_s"] == 1
    assert payload["cop"] == 3.1
    assert payload["heating_capacity_W"] == round(_CONDENSER_DUTY, 6)
    assert payload["capacity_kW"] == round(_CONDENSER_DUTY / 1000, 6)


def test_thermo_tools_report_missing_coolprop(tmp_path: Path, monkeypatch) -> None:
    def missing():
        raise ImportError("no coolprop")

    monkeypatch.setattr("openbuild_tools.fluids.load_coolprop", missing)
    lookup = fluid_properties({
        "fluid": "R290",
        "queries": [{"name": "state", "temperature_C": 0, "quality": 1}],
    })
    cycle = refrigeration_cycle(tmp_path, {
        "fluid": "R290",
        "evaporator_C": -10,
        "condenser_C": 40,
        "mode": "cooling",
        "capacity_W": 1000,
    })

    assert "CoolProp is not installed" in lookup
    assert "CoolProp is not installed" in cycle
    assert not (tmp_path / "cycle.json").exists()


def test_skid_bbox_scales_with_cycle(tmp_path: Path) -> None:
    geometry = tmp_path / "geometry"
    geometry.mkdir()
    template = Path(__file__).resolve().parents[2] / "templates" / "part.py"
    (geometry / "part.py").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "cycle.json").write_text(json.dumps({"capacity_kW": 20}), encoding="utf-8")

    compile_geometry(tmp_path, "geometry/part.py")
    payload = json.loads((geometry / ".openbuild-result.json").read_text(encoding="utf-8"))

    assert payload["ok"] is True
    assert payload["bbox"] == {"x": 2400, "y": 1200, "z": 1000}


class _CycleCoolProp:
    def PropsSI(self, output, first, _first_value, second, second_value, _fluid):
        if output == "P" and second == "Q":
            return 300000.0 if second_value == 1 else 1500000.0
        if output == "S":
            return 1700.0
        if output == "H" and first == "P" and second == "S":
            return 450000.0
        if output == "H" and first == "T" and second == "P":
            return 400000.0 if second_value < 1000000 else 250000.0
        raise AssertionError((output, first, second))


_CONDENSER_DUTY = 400000.0 + (50000.0 / 0.7) - 250000.0


def test_datasheet_url_must_be_http(tmp_path: Path) -> None:
    message = import_datasheet(tmp_path, {"url": "ftp://example.com/sheet.pdf"})
    assert message.startswith("rejected:")
    assert "http or https" in message
    assert not (tmp_path / "catalog" / "components.json").exists()


def test_datasheet_path_escape_is_rejected(tmp_path: Path) -> None:
    message = import_datasheet(tmp_path, {"path": "../secret.pdf"})
    assert message.startswith("rejected:")
    assert not (tmp_path.parent / "secret.pdf").exists()


def test_import_datasheet_returns_text_without_catalog(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("openbuild_tools.catalog.download_pdf", lambda _url: b"%PDF")
    monkeypatch.setattr("openbuild_tools.catalog.extract_text", lambda _data: "OSK5341-K cooling capacity")
    message = import_datasheet(tmp_path, {"url": "https://www.bitzer.de/shared_media/documentation/sp-500-5-en.pdf"})
    assert message.startswith("saved catalog/sources/sp-500-5-en.pdf\n")
    assert "OSK5341-K" in message
    assert (tmp_path / "catalog" / "sources" / "sp-500-5-en.pdf").read_bytes() == b"%PDF"
    assert not (tmp_path / "catalog" / "components.json").exists()


def _compressor() -> dict:
    return {
        "partNumber": "OSK5341-K",
        "manufacturer": "Bitzer",
        "category": "compressor",
        "description": "Open screw compressor",
        "displacement_m3_h": 84,
        "ratings": [
            {"fluid": "R1234yf", "evaporator_C": 5, "condenser_C": 50, "capacity_W": 44500},
            {"fluid": "R448A", "evaporator_C": -10, "condenser_C": 45, "capacity_W": 42900},
        ],
        "source": {"url": "https://www.bitzer.de/shared_media/documentation/sp-500-5-en.pdf"},
    }


def test_write_catalog_merges_ratings_by_part_number(tmp_path: Path) -> None:
    first = write_catalog(tmp_path, [_compressor()])
    assert first == "wrote 1 items to catalog/components.json"
    updated = dict(_compressor())
    updated["weight_kg"] = 65
    second = write_catalog(tmp_path, [updated])
    assert second == "wrote 1 items to catalog/components.json"
    rows = json.loads((tmp_path / "catalog" / "components.json").read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["weight_kg"] == 65
    assert rows[0]["ratings"] == _compressor()["ratings"]


def test_search_catalog_matches_only_published_points(tmp_path: Path) -> None:
    write_catalog(tmp_path, [_compressor()])
    matched = search_catalog(tmp_path, {
        "category": "compressor",
        "refrigerant": "R448A",
        "evaporator_C": -10,
        "condenser_C": 45,
        "min_capacity_W": 40000,
    })
    assert "OSK5341-K" in matched
    assert "42900 W" in matched

    other_fluid = search_catalog(tmp_path, {
        "refrigerant": "R290",
        "evaporator_C": -10,
        "condenser_C": 40,
        "min_capacity_W": 15000,
    })
    assert other_fluid == "no catalog components match"

    other_temperature = search_catalog(tmp_path, {
        "refrigerant": "R448A",
        "evaporator_C": -10,
        "condenser_C": 40,
        "min_capacity_W": 1000,
    })
    assert other_temperature == "no catalog components match"


def test_tool_schemas_are_explicit() -> None:
    assert [tool.name for tool in TOOLS] == [
        "compile_geometry",
        "export_step",
        "validate",
        "fluid_properties",
        "refrigeration_cycle",
        "import_datasheet",
        "write_catalog",
        "search_catalog",
        "write_bom",
    ]
    compile_schema = TOOLS[0].input_schema
    assert compile_schema["required"] == ["script"]
    assert compile_schema["additionalProperties"] is False
