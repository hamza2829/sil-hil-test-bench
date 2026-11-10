# Bench requirements

All values refer to the simulated chamber and the supplied YAML recipe. A trip must be evaluated from the sensor values delivered to the controller.

1. **R-001** The fixed-step clock shall produce 400 samples at 0.25 s intervals, starting at simulated time zero.
2. **R-002** Seeded noise shall reproduce the same instrument readings for the same seed. Changing the seed shall change readings without changing the true state at the initial tick.
3. **R-003** Full heater power shall raise true temperature above ambient. Removing power shall cool a hot chamber toward ambient.
4. **R-004** Opening the inlet shall raise true gas flow and, subsequently, true pressure relative to a closed inlet.
5. **R-005** The normal ramp shall command 25 °C at 0 s, 47.5 °C at 15 s, and 70 °C from 30 s onward. True temperature shall stay within 2 °C of 70 °C over the final 10 s without a trip.
6. **R-006** The PID shall constrain heater demand to [0, 1] and avoid accumulating integral error while the output is saturated in the direction of the error.
7. **R-007** With the normal 24 sccm flow setpoint, true flow shall stay within 1 sccm of target over the final 10 s.
8. **R-008** In the sensor drift scenario, the temperature reading shall cross 100 °C while true temperature stays below 100 °C. The controller shall trip and command both outputs to zero in the crossing tick.
9. **R-009** In the stuck-open valve scenario, the controller shall trip at the first pressure reading of at least 27 mbar and command both outputs to zero. The applied valve shall remain open due to the mechanical fault.
10. **R-010** In the heat pulse scenario, the true temperature shall jump to 115 °C at 18 s. The controller shall trip and remove heater power and valve demand in that tick.
11. **R-011** In the stuck-closed valve scenario, the controller shall trip at the first pressure reading of at most 10 mbar and command both outputs to zero.
12. **R-012** A trip shall latch for the lifetime of the controller instance, including after all sensor readings return to the safe range.
13. **R-013** The heater Modbus unit shall expose temperature at input address 0 in hundredths of a degree and accept heater demand at holding address 0 in thousandths of full power.
14. **R-014** The gauge Modbus unit shall expose pressure and flow at input addresses 0 and 1 in hundredths of their units, and accept inlet demand at holding address 0 in thousandths of full opening.
15. **R-015** A non-finite measurement supplied to the controller shall latch an invalid-measurement trip and command both outputs to zero.
16. **R-016** On the normal recipe, true SIL and HIL traces shall agree within 0.15 °C, 0.05 mbar, and 0.2 sccm at each tick.
17. **R-017** The controller shall trip on exact boundary values of 100 °C, 10 mbar, and 27 mbar. Readings strictly inside these limits shall permit control.
