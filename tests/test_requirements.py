import asyncio
from functools import cache
from math import inf, nan

import pytest
import pytest_html
from pymodbus.client import AsyncModbusTcpClient

from bench.case_design import load_designs, write_comparison
from bench.controller import Controller, Setpoints, TemperaturePID
from bench.modbus_io import serve_virtual_devices
from bench.model import Chamber, Outputs, Reading
from bench.runner import run_scenario
from bench.scenarios import load_scenarios

SCENARIOS = load_scenarios()
REQUIREMENTS, DESIGNS = load_designs()
OFF = Outputs(0, 0)


def clock(trace):
    assert [sample.time_s for sample in trace] == [index * 0.25 for index in range(400)]


def noise():
    a, b, c = Chamber(42), Chamber(42), Chamber(43)
    assert a.state == b.state == c.state
    readings_a, readings_b, readings_c = ([chamber.measure() for _ in range(8)] for chamber in (a, b, c))
    assert readings_a == readings_b
    assert readings_a != readings_c
    assert len(set(readings_a)) > 1
    assert a.state == b.state == c.state


def heater_model():
    chamber = Chamber(42)
    ambient = chamber.state.temperature_c
    chamber.step(Outputs(1, 0), 0.25)
    hot = chamber.state.temperature_c
    assert hot > ambient
    chamber.step(OFF, 0.25)
    assert ambient < chamber.state.temperature_c < hot


def flow_model():
    open_inlet, closed_inlet = Chamber(42), Chamber(42)
    open_inlet.step(Outputs(0, 1), 0.25)
    closed_inlet.step(OFF, 0.25)
    assert open_inlet.state.flow_sccm > closed_inlet.state.flow_sccm
    open_inlet.step(Outputs(0, 1), 0.25)
    closed_inlet.step(OFF, 0.25)
    assert open_inlet.state.pressure_mbar > closed_inlet.state.pressure_mbar


def ramp(trace):
    assert trace[0].setpoints.temperature_c == 25
    assert trace[60].setpoints.temperature_c == 47.5
    assert all(sample.setpoints.temperature_c == 70 for sample in trace[120:])
    assert all(sample.trip is None for sample in trace)
    assert max(abs(sample.state.temperature_c - 70) for sample in trace[-40:]) <= 2


def pid():
    controller = TemperaturePID()
    for _ in range(400):
        assert controller.update(200, 25, 0.25) == 1
    assert controller.update(25, 25, 0.25) == 0
    for _ in range(400):
        assert controller.update(0, 25, 0.25) == 0
    assert 0 < controller.update(26, 25, 0.25) < 1


def flow(trace):
    assert all(sample.setpoints.flow_sccm == 24 for sample in trace)
    assert max(abs(sample.state.flow_sccm - 24) for sample in trace[-40:]) <= 1


def assert_first_trip(trace, index, cause, applied=OFF):
    assert all(sample.trip is None for sample in trace[:index])
    assert trace[index].trip == cause
    assert trace[index].commanded == OFF
    assert trace[index].applied == applied


def drift(trace):
    index = next((i for i, sample in enumerate(trace) if sample.reading.temperature_c >= 100), None)
    assert index is not None, "Drifting sensor never reached 100 °C"
    assert max(sample.state.temperature_c for sample in trace) < 100
    assert_first_trip(trace, index, "over_temperature")


def stuck_open(trace):
    index = next((i for i, sample in enumerate(trace) if sample.reading.pressure_mbar >= 27), None)
    assert index is not None, "Pressure never reached 27 mbar"
    assert trace[59].applied.valve < 1
    assert_first_trip(trace, index, "high_pressure", applied=Outputs(0, 1))
    assert all(sample.applied.valve == 1 for sample in trace[60:])


def heat_pulse(trace):
    assert trace[71].state.temperature_c < 100
    assert trace[72].time_s == 18
    assert trace[72].state.temperature_c == 115
    assert_first_trip(trace, 72, "over_temperature")


def stuck_closed(trace):
    index = next((i for i, sample in enumerate(trace) if sample.reading.pressure_mbar <= 10), None)
    assert index is not None, "Pressure never dropped to 10 mbar"
    assert trace[60].commanded.valve > 0 and trace[60].applied.valve == 0
    assert_first_trip(trace, index, "low_pressure")


def latch(trace):
    after_pulse = trace[73:]
    assert any(s.reading.temperature_c < 100 and 10 < s.reading.pressure_mbar < 27 for s in after_pulse)
    assert all(s.trip == "over_temperature" and s.commanded == s.applied == OFF for s in after_pulse)


async def register_round_trip(unit, expected, value, applied):
    async with serve_virtual_devices() as (devices, port):
        devices.publish(Reading(71.23, 18.45, 24.56))
        async with AsyncModbusTcpClient("127.0.0.1", port=port, timeout=2, retries=0) as client:
            reading = await client.read_input_registers(0, count=len(expected), device_id=unit)
            assert not reading.isError()
            assert reading.registers == expected
            response = await client.write_register(0, value, device_id=unit)
            assert not response.isError()
            demand = await client.read_holding_registers(0, count=1, device_id=unit)
            assert not demand.isError()
            assert demand.registers == [value]
            assert devices.outputs() == applied


def heater_registers():
    asyncio.run(register_round_trip(1, [7123], 625, Outputs(0.625, 0)))


def gauge_registers():
    asyncio.run(register_round_trip(2, [1845, 2456], 410, Outputs(0, 0.410)))


def nonfinite():
    for invalid in (Reading(nan, 20, 24), Reading(70, inf, 24), Reading(70, 20, -inf)):
        controller = Controller()
        target = Setpoints(70, 24)
        assert controller.update(invalid, target, 0.25) == OFF
        assert controller.trip == "invalid_measurement"
        assert controller.update(Reading(65, 20, 24), target, 0.25) == OFF
        assert controller.trip == "invalid_measurement"


def parity(sil, hil):
    for direct, network in zip(sil, hil, strict=True):
        assert direct.time_s == network.time_s
        assert network.state.temperature_c == pytest.approx(direct.state.temperature_c, abs=0.15)
        assert network.state.pressure_mbar == pytest.approx(direct.state.pressure_mbar, abs=0.05)
        assert network.state.flow_sccm == pytest.approx(direct.state.flow_sccm, abs=0.2)


def limits():
    target = Setpoints(70, 24)
    for reading, trip in (
        (Reading(100, 20, 24), "over_temperature"),
        (Reading(69, 10, 24), "low_pressure"),
        (Reading(69, 27, 24), "high_pressure"),
    ):
        controller = Controller()
        assert controller.update(reading, target, 0.25) == OFF
        assert controller.trip == trip
    for pressure in (10.01, 26.99):
        controller = Controller()
        outputs = controller.update(Reading(99.99, pressure, 24), target, 0.25)
        assert controller.trip is None
        assert outputs.valve > 0


CHECKS = {check.__name__: check for check in (
    clock, noise, heater_model, flow_model, ramp, pid, flow, drift, stuck_open, heat_pulse,
    stuck_closed, latch, heater_registers, gauge_registers, nonfinite, parity, limits,
)}


@pytest.fixture(scope="session")
def trace_for():
    @cache
    def run(name, mode):
        return asyncio.run(run_scenario(SCENARIOS[name], mode))

    return run


@pytest.mark.parametrize("source,case,mode", [
    pytest.param(source, case, mode, id="-".join(filter(None, (source, case.id, case.requirement, mode, case.scenario))))
    for source, cases in DESIGNS.items()
    for case in cases
    for mode in case.modes
])
def test_requirement(source, case, mode, trace_for, json_metadata, extras):
    metadata = {
        "design": source, "case": case.id, "requirement": case.requirement,
        "check": case.check, "mode": mode, "scenario": case.scenario,
    }
    json_metadata.update(metadata)
    check = CHECKS[case.check]
    if case.scenario is None:
        extras.append(pytest_html.extras.json(metadata, name="Case details"))
        check()
    elif mode == "cross-mode":
        extras.append(pytest_html.extras.json(metadata, name="Case details"))
        check(trace_for(case.scenario, "sil"), trace_for(case.scenario, "hil"))
    else:
        trace = trace_for(case.scenario, mode)
        trip = next((sample for sample in trace if sample.trip), None)
        evidence = {
            "samples": len(trace), "first_trip": trip.trip if trip else None,
            "first_trip_s": trip.time_s if trip else None,
        }
        json_metadata.update(evidence)
        extras.append(pytest_html.extras.json(metadata | evidence, name="Case details"))
        check(trace)


def test_case_designs(tmp_path):
    assert len(REQUIREMENTS) >= 15
    assert {case.requirement for case in DESIGNS["manual"]} == {req.id for req in REQUIREMENTS}
    for cases in DESIGNS.values():
        for case in cases:
            assert case.check in CHECKS
            assert set(case.modes) <= {"sil", "hil", "unit", "cross-mode"}
        for mode in ("sil", "hil"):
            assert {case.scenario for case in cases if mode in case.modes and case.scenario} == set(SCENARIOS)

    first, second = tmp_path / "first", tmp_path / "second"
    write_comparison(first)
    write_comparison(second)
    for artifact in ("mock-cases.json", "coverage.json", "coverage.md"):
        assert (first / artifact).read_bytes() == (second / artifact).read_bytes()
