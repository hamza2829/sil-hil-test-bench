# SIL and HIL test bench

An entirely simulated test bench for a thin-film deposition chamber. The chamber, heater controller, pressure gauge, and all measurements are synthetic. This project uses no real equipment, AIXTRON data, or semiconductor process data. The model covers temperature, pressure, and gas flow. It omits deposition chemistry and film growth.

## Run the bench

The [GitHub Actions workflow](.github/workflows/bench.yml) runs automatically on pushes and pull requests on Linux and Windows with Python 3.12. It uses public Python dependencies and localhost TCP. The bench requires no service accounts, API keys, repository secrets, Docker, or manual device setup.

From the repository root, with Python 3.12 selected:

```sh
python -m pip install -r requirements.txt
python -m bench.case_design
python -m pytest
```

Each pytest run writes `artifacts/protocol.html` and `artifacts/protocol.json`. Both report the result of each collected test. Scenario cases include the design source, requirement ID, mode, scenario, and first trip time when applicable. A protective trip in a fault scenario passes when it matches the requirement. CI uploads the files with the coverage comparison as `bench-reports-ubuntu-latest` and `bench-reports-windows-latest`, including when assertions fail.

## Model and control loop

The model advances by explicit Euler integration every 0.25 simulated seconds. Heater power adds heat and the chamber loses heat toward 25 °C. Inlet flow responds gradually to valve opening, and pressure tends toward a base pressure plus a term proportional to flow. A seeded random generator adds instrument noise. The trace keeps the true state, measured state, commanded outputs, and applied outputs separate.

The same controller runs in both modes. A PID with anti-windup drives the heater, while proportional feedback and feedforward regulate flow through the inlet valve. A temperature reading at or above 100 °C or a pressure reading outside the open interval from 10 to 27 mbar latches a trip and commands both outputs to zero. A mechanically stuck valve can still stay open after the controller commands it closed.

| Mode | How the controller receives measurements and sends commands |
| --- | --- |
| SIL | Direct Python calls in the same process as the simulated plant. |
| HIL-style | Real Modbus TCP exchanges with two simulated devices on `127.0.0.1`. The harness binds an ephemeral port, publishes measurements, and advances the plant from the actuator registers. |

The virtual devices run inside the test harness. Both modes advance on simulated ticks without waiting for wall-clock time. The HIL-style tests exercise the protocol, register map, and quantization. Real device behavior and timing are outside the scope of the bench.

| Unit ID | Input registers (FC 04) | Holding registers (FC 03 read, FC 06 write) |
| --- | --- | --- |
| 1 · Heater controller | `0` temperature in 0.01 °C | `0` heater demand from 0 to 1000 |
| 2 · Pressure gauge and virtual gas controls | `0` pressure in 0.01 mbar, `1` flow in 0.01 sccm | `0` inlet demand from 0 to 1000 |

Addresses are zero-based. Registers are unsigned 16-bit integers. A demand of 1000 represents full power or full opening.

## Scenarios

Both modes execute every case in [scenarios.yaml](scenarios.yaml).

| Scenario | Expected behavior |
| --- | --- |
| `normal_ramp` | Track the 25–70 °C ramp and 24 sccm flow without tripping. |
| `sensor_drift` | A growing temperature bias triggers shutdown while true temperature is below the limit. |
| `stuck_valve` | A mechanically open inlet raises pressure until the high-pressure trip. |
| `over_temperature` | A heat pulse brings true temperature to 115 °C and triggers shutdown in the same tick. |
| `low_pressure` | A mechanically closed inlet lowers pressure until the low-pressure trip. |

## Test design coverage

The [requirements](spec/requirements.md) define 17 numbered, testable behaviors. The [hand-authored design](spec/manual_cases.json) covers all 17. The offline `MockLLM` covers 12 of 17 by matching requirement prose to predefined test templates. Its missing requirements cover PID anti-windup, trip latching, invalid measurements, SIL/HIL agreement, and exact interlock boundaries.

The `CaseGenerator` interface accepts parsed requirements and returns case definitions. The mock is a deterministic stand-in for AI-assisted drafting and makes no API calls. Both designs execute through pytest against a shared set of assertion functions. `artifacts/mock-cases.json` contains the generated design, and `artifacts/coverage.md` and `artifacts/coverage.json` map each requirement to its cases. Coverage counts requirement references. The protocols record which checks passed.
