"""Run the same sampled controller and plant in SIL or HIL-style mode."""

from dataclasses import dataclass
from typing import Literal

from .controller import Controller, Setpoints
from .modbus_io import LOOPBACK, ModbusChamberIO, VirtualDevices, connect_chamber, serve_virtual_devices
from .model import Chamber, Outputs, Reading
from .scenarios import Scenario

Mode = Literal["sil", "hil"]


@dataclass(frozen=True)
class Sample:
    time_s: float
    state: Reading
    reading: Reading
    setpoints: Setpoints
    commanded: Outputs
    applied: Outputs
    trip: str | None


async def run_scenario(scenario: Scenario, mode: Mode) -> list[Sample]:
    if mode == "sil":
        return await _run(scenario)
    if mode == "hil":
        async with serve_virtual_devices() as (devices, port):
            async with connect_chamber(LOOPBACK, port) as io:
                return await _run(scenario, devices=devices, io=io)
    raise ValueError(f"Unknown bench mode {mode!r}")


async def _run(
    scenario: Scenario, *, devices: VirtualDevices | None = None, io: ModbusChamberIO | None = None,
) -> list[Sample]:
    chamber = Chamber(scenario.seed)
    controller = Controller()
    samples = []
    for tick in range(scenario.steps):
        time_s = tick * scenario.dt_s
        fault = scenario.fault
        bias = 0.0
        stuck_valve = None
        if fault is not None and tick >= fault.tick:
            if fault.kind == "temperature_drift":
                bias = fault.value * (tick - fault.tick) * scenario.dt_s
            elif fault.kind == "stuck_valve":
                stuck_valve = fault.value
            elif tick == fault.tick:
                chamber.heat_pulse(fault.value)

        reading = chamber.measure(bias)
        if devices is not None and io is not None:
            devices.publish(reading)
            reading = await io.measure()
        setpoints = scenario.recipe.setpoints(time_s)
        commanded = controller.update(reading, setpoints, scenario.dt_s)
        outputs = commanded
        if devices is not None and io is not None:
            await io.actuate(commanded)
            outputs = devices.outputs()
        applied = Outputs(outputs.heater, outputs.valve if stuck_valve is None else stuck_valve)
        samples.append(Sample(time_s, chamber.state, reading, setpoints, commanded, applied, controller.trip))
        chamber.step(applied, scenario.dt_s)
    return samples
