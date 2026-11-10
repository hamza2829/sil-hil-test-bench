"""Build and compare executable test designs from the Markdown requirements."""

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence

SPEC_DIR = Path(__file__).resolve().parents[1] / "spec"
REQUIREMENT_LINE = re.compile(r"^(\d+)\. \*\*(R-\d{3})\*\* (.+)$", re.MULTILINE)
BOTH_MODES = ("sil", "hil")


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str


@dataclass(frozen=True)
class Case:
    id: str
    requirement: str
    check: str
    modes: tuple[str, ...]
    scenario: str | None = None


class CaseGenerator(Protocol):
    def generate(self, requirements: Sequence[Requirement]) -> list[Case]: ...


class MockLLM:
    """Offline stand-in that matches requirement prose to predefined test templates."""

    templates = (
        ("fixed-step clock", "clock", BOTH_MODES, "normal_ramp"),
        ("seeded noise", "noise", ("unit",), None),
        ("full heater power", "heater_model", ("unit",), None),
        ("opening the inlet", "flow_model", ("unit",), None),
        ("normal ramp", "ramp", BOTH_MODES, "normal_ramp"),
        ("flow setpoint", "flow", BOTH_MODES, "normal_ramp"),
        ("sensor drift scenario", "drift", BOTH_MODES, "sensor_drift"),
        ("stuck-open valve scenario", "stuck_open", BOTH_MODES, "stuck_valve"),
        ("heat pulse scenario", "heat_pulse", BOTH_MODES, "over_temperature"),
        ("stuck-closed valve scenario", "stuck_closed", BOTH_MODES, "low_pressure"),
        ("heater modbus unit", "heater_registers", ("hil",), None),
        ("gauge modbus unit", "gauge_registers", ("hil",), None),
    )

    def generate(self, requirements: Sequence[Requirement]) -> list[Case]:
        cases = []
        for requirement in requirements:
            for phrase, check, modes, scenario in self.templates:
                if phrase in requirement.text.lower():
                    cases.append(Case(f"A-{requirement.id[2:]}-{check}", requirement.id, check, modes, scenario))
        return cases


def read_requirements(path: Path = SPEC_DIR / "requirements.md") -> list[Requirement]:
    matches = REQUIREMENT_LINE.findall(path.read_text(encoding="utf-8"))
    if not matches or any(
        int(number) != index or requirement != f"R-{index:03d}"
        for index, (number, requirement, _) in enumerate(matches, start=1)
    ):
        raise ValueError("Requirements must have consecutive numbered IDs starting at R-001")
    return [Requirement(requirement, text) for _, requirement, text in matches]


def load_designs(generator: CaseGenerator | None = None) -> tuple[list[Requirement], dict[str, list[Case]]]:
    requirements = read_requirements()
    manual = json.loads((SPEC_DIR / "manual_cases.json").read_text(encoding="utf-8"))
    if generator is None:
        generator = MockLLM()
    designs = {
        "manual": [Case(**{**item, "modes": tuple(item["modes"])}) for item in manual],
        "mock": generator.generate(requirements),
    }
    known_requirements = {requirement.id for requirement in requirements}
    for source, cases in designs.items():
        if len({case.id for case in cases}) != len(cases):
            raise ValueError(f"Duplicate case IDs in {source} design")
        for case in cases:
            if case.requirement not in known_requirements:
                raise ValueError(f"Unknown requirement {case.requirement} in case {case.id}")
            if not case.modes or len(set(case.modes)) != len(case.modes):
                raise ValueError(f"Missing or duplicated execution modes for case {case.id}")
    return requirements, designs


def write_comparison(directory: Path, generator: CaseGenerator | None = None) -> None:
    requirements, designs = load_designs(generator)
    matrix = [
        {
            "requirement": requirement.id,
            "text": requirement.text,
            **{
                source: [case.id for case in cases if case.requirement == requirement.id]
                for source, cases in designs.items()
            },
        }
        for requirement in requirements
    ]
    totals = {
        source: {
            "covered": sum(bool(row[source]) for row in matrix),
            "missing": [row["requirement"] for row in matrix if not row[source]],
        }
        for source in designs
    }
    lines = ["# Test design coverage", "", "A requirement is covered when a case references it. See the test protocol for execution results.", ""]
    for source, total in totals.items():
        lines.append(f"- {source.title()} design covers {total['covered']} of {len(matrix)} requirements.")
    lines.extend(["", "| Requirement | Manual cases | Mock cases |", "| --- | --- | --- |"])
    for row in matrix:
        lines.append(f"| {row['requirement']} | {', '.join(row['manual']) or 'Missing'} | {', '.join(row['mock']) or 'Missing'} |")

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "mock-cases.json").write_text(json.dumps([asdict(case) for case in designs["mock"]], indent=2) + "\n", encoding="utf-8")
    (directory / "coverage.json").write_text(json.dumps({"total": len(matrix), "designs": totals, "requirements": matrix}, indent=2) + "\n", encoding="utf-8")
    (directory / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    write_comparison(parser.parse_args().output)
