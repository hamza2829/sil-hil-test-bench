"""Lumped-parameter chamber and synthetic instruments."""

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class Reading:
    temperature_c: float
    pressure_mbar: float
    flow_sccm: float


@dataclass(frozen=True)
class Outputs:
    heater: float
    valve: float


AMBIENT_C = 25.0
BASE_PRESSURE_MBAR = 8.0
MAX_FLOW_SCCM = 60.0
SAFE_OUTPUTS = Outputs(0.0, 0.0)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


class Chamber:
    def __init__(self, seed: int):
        self.state = Reading(AMBIENT_C, 15.0, 0.0)
        self.noise = Random(seed)

    def measure(self, temperature_bias_c: float = 0.0) -> Reading:
        temperature, pressure, flow = (
            self.state.temperature_c + temperature_bias_c + self.noise.gauss(0, 0.06),
            self.state.pressure_mbar + self.noise.gauss(0, 0.03),
            self.state.flow_sccm + self.noise.gauss(0, 0.12),
        )
        return Reading(max(0, temperature), max(0, pressure), max(0, flow))

    def heat_pulse(self, temperature_c: float) -> None:
        self.state = Reading(
            max(temperature_c, self.state.temperature_c),
            self.state.pressure_mbar,
            self.state.flow_sccm,
        )

    def step(self, outputs: Outputs, dt_s: float) -> None:
        old = self.state
        # Explicit Euler integration. The three rates use the previous state.
        heating = 4.0 * outputs.heater - (old.temperature_c - AMBIENT_C) / 20.0
        inflow = (MAX_FLOW_SCCM * outputs.valve - old.flow_sccm) / 1.5
        pressure_change = (BASE_PRESSURE_MBAR + 0.5 * old.flow_sccm - old.pressure_mbar) / 4.0
        self.state = Reading(
            old.temperature_c + dt_s * heating,
            old.pressure_mbar + dt_s * pressure_change,
            old.flow_sccm + dt_s * inflow,
        )
