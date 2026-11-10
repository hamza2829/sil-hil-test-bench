"""Load a fixed-step recipe and fault definitions from YAML."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from .controller import Setpoints
from .model import MAX_FLOW_SCCM, clamp

SCENARIO_FILE = Path(__file__).resolve().parents[1] / "scenarios.yaml"


@dataclass(frozen=True)
class Recipe:
    start_c: float
    target_c: float
    ramp_s: float
    flow_sccm: float

    def setpoints(self, time_s: float) -> Setpoints:
        fraction = clamp(time_s / self.ramp_s)
        return Setpoints(self.start_c + fraction * (self.target_c - self.start_c), self.flow_sccm)


@dataclass(frozen=True)
class Fault:
    kind: str
    tick: int
    value: float

    def __post_init__(self):
        bounds = {"temperature_drift": (0, 5), "stuck_valve": (0, 1), "heat_pulse": (25, 200)}
        if self.kind not in bounds:
            raise ValueError(f"Unknown fault kind {self.kind!r}")
        low, high = bounds[self.kind]
        if not low <= self.value <= high:
            raise ValueError(f"Fault {self.kind!r} value must be in [{low}, {high}]")


@dataclass(frozen=True)
class Scenario:
    name: str
    dt_s: float
    steps: int
    seed: int
    recipe: Recipe
    fault: Fault | None

    def __post_init__(self):
        if not 0 < self.dt_s <= 1 or type(self.steps) is not int or self.steps <= 0:
            raise ValueError("Use a time step in (0, 1] seconds and a positive integer step count")
        if not 0 < self.recipe.ramp_s <= self.steps * self.dt_s:
            raise ValueError("The ramp must fit within the run")
        if not 0 <= self.recipe.flow_sccm <= MAX_FLOW_SCCM:
            raise ValueError("Flow setpoint is outside the simulated instrument range")
        if not all(0 <= value <= 200 for value in (self.recipe.start_c, self.recipe.target_c)):
            raise ValueError("Temperature setpoints must be within [0, 200] °C")
        if self.fault and (type(self.fault.tick) is not int or not 0 <= self.fault.tick < self.steps):
            raise ValueError("Fault tick must be an integer within the run")


def load_scenarios(path: Path = SCENARIO_FILE) -> dict[str, Scenario]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    recipe = Recipe(**data["recipe"])
    return {
        name: Scenario(name, recipe=recipe, fault=Fault(**fault) if fault is not None else None, **data["clock"])
        for name, fault in data["scenarios"].items()
    }
