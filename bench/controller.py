"""Transport-independent temperature PID, flow control, and interlocks."""

from dataclasses import dataclass
from math import isfinite

from .model import MAX_FLOW_SCCM, SAFE_OUTPUTS, Outputs, Reading, clamp

MAX_TEMPERATURE_C = 100.0
MIN_PRESSURE_MBAR = 10.0
MAX_PRESSURE_MBAR = 27.0


@dataclass(frozen=True)
class Setpoints:
    temperature_c: float
    flow_sccm: float


class TemperaturePID:
    def __init__(self):
        self.integral = 0.0
        self.previous_temperature: float | None = None

    def update(self, target_c: float, measured_c: float, dt_s: float) -> float:
        error = target_c - measured_c
        rate = 0.0
        if self.previous_temperature is not None:
            rate = (measured_c - self.previous_temperature) / dt_s
        self.previous_temperature = measured_c
        proportional_and_derivative = 0.055 * error - 0.014 * rate
        candidate = self.integral + 0.004 * error * dt_s
        proposed = proportional_and_derivative + candidate
        # Freeze the integral only when error would push farther into saturation.
        if not ((proposed > 1 and error > 0) or (proposed < 0 and error < 0)):
            self.integral = candidate
        return clamp(proportional_and_derivative + self.integral)


class Controller:
    def __init__(self):
        self.pid = TemperaturePID()
        self.trip: str | None = None

    def update(self, reading: Reading, setpoints: Setpoints, dt_s: float) -> Outputs:
        if self.trip is None:
            self.trip = self.interlock(reading)
        if self.trip is not None:
            return SAFE_OUTPUTS
        heater = self.pid.update(setpoints.temperature_c, reading.temperature_c, dt_s)
        valve = setpoints.flow_sccm / MAX_FLOW_SCCM
        valve += 0.012 * (setpoints.flow_sccm - reading.flow_sccm)
        return Outputs(heater, clamp(valve))

    @staticmethod
    def interlock(reading: Reading) -> str | None:
        if not all(map(isfinite, (reading.temperature_c, reading.pressure_mbar, reading.flow_sccm))):
            return "invalid_measurement"
        if reading.temperature_c >= MAX_TEMPERATURE_C:
            return "over_temperature"
        if reading.pressure_mbar >= MAX_PRESSURE_MBAR:
            return "high_pressure"
        if reading.pressure_mbar <= MIN_PRESSURE_MBAR:
            return "low_pressure"
        return None
