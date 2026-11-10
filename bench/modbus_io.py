"""PyModbus TCP client and localhost virtual instruments for the bench."""

from contextlib import asynccontextmanager

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ModbusTcpServer

from .model import Outputs, Reading

LOOPBACK = "127.0.0.1"
HEATER_UNIT = 1
GAUGE_UNIT = 2
SENSOR_SCALE = 100
COMMAND_SCALE = 1000


class ModbusChamberIO:
    """Controller-side adapter. Every read and command goes through TCP."""

    def __init__(self, client: AsyncModbusTcpClient):
        self.client = client

    async def measure(self) -> Reading:
        heater = await self.client.read_input_registers(0, count=1, device_id=HEATER_UNIT)
        self._check(heater)
        gauge = await self.client.read_input_registers(0, count=2, device_id=GAUGE_UNIT)
        self._check(gauge)
        return Reading(
            heater.registers[0] / SENSOR_SCALE,
            gauge.registers[0] / SENSOR_SCALE,
            gauge.registers[1] / SENSOR_SCALE,
        )

    async def actuate(self, outputs: Outputs) -> None:
        heater = await self.client.write_register(0, round(outputs.heater * COMMAND_SCALE), device_id=HEATER_UNIT)
        self._check(heater)
        valve = await self.client.write_register(0, round(outputs.valve * COMMAND_SCALE), device_id=GAUGE_UNIT)
        self._check(valve)

    @staticmethod
    def _check(response) -> None:
        if response.isError():
            raise OSError(f"Modbus transaction failed: {response}")


class VirtualDevices:
    """Bench-side register store for the two simulated Modbus unit IDs."""

    def __init__(self):
        # PyModbus offsets protocol address zero to datastore address one.
        self.context = ModbusServerContext(devices={
            HEATER_UNIT: ModbusDeviceContext(
                ir=ModbusSequentialDataBlock(1, [0]), hr=ModbusSequentialDataBlock(1, [0]),
            ),
            GAUGE_UNIT: ModbusDeviceContext(
                ir=ModbusSequentialDataBlock(1, [0, 0]), hr=ModbusSequentialDataBlock(1, [0]),
            ),
        }, single=False)

    def publish(self, reading: Reading) -> None:
        self.context[HEATER_UNIT].setValues(4, 0, [round(reading.temperature_c * SENSOR_SCALE)])
        self.context[GAUGE_UNIT].setValues(4, 0, [
            round(reading.pressure_mbar * SENSOR_SCALE), round(reading.flow_sccm * SENSOR_SCALE),
        ])

    def outputs(self) -> Outputs:
        heater = self.context[HEATER_UNIT].getValues(3, 0, 1)[0]
        valve = self.context[GAUGE_UNIT].getValues(3, 0, 1)[0]
        if not (0 <= heater <= COMMAND_SCALE and 0 <= valve <= COMMAND_SCALE):
            raise ValueError("Virtual actuator command is outside [0, 1000]")
        return Outputs(heater / COMMAND_SCALE, valve / COMMAND_SCALE)


@asynccontextmanager
async def serve_virtual_devices():
    devices = VirtualDevices()
    server = ModbusTcpServer(devices.context, address=(LOOPBACK, 0))
    try:
        await server.serve_forever(background=True)
        port = server.transport.sockets[0].getsockname()[1]
        yield devices, port
    finally:
        await server.shutdown()


@asynccontextmanager
async def connect_chamber(host: str, port: int):
    client = AsyncModbusTcpClient(host, port=port, timeout=2, retries=0, reconnect_delay=0)
    try:
        if not await client.connect():
            raise ConnectionError(f"Cannot connect to Modbus at {host}:{port}")
        yield ModbusChamberIO(client)
    finally:
        client.close()
