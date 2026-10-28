"""One tick of the read-setpoints -> step-plant -> write-outputs loop."""

from typing import Protocol
from contracts.signals import PlantInputs, PlantOutputs, READ_REGISTERS, WRITE_REGISTERS
from orchestrator.plant_model import PlantModel
from orchestrator.disturbance import generate_disturbance
from orchestrator.network import network_heat_demand, network_temperatures


class ModbusIO(Protocol):
    """Minimal Modbus register I/O needed by run_tick (real client or fake)."""

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        """Args:
            address: Zero-based Modbus register address to start reading at.
            count: Number of consecutive registers to read.

        Returns:
            Raw register values as a list of ints.
        """
        ...

    def write_registers(self, address: int, values: list[int]) -> None:
        """Args:
            address: Zero-based Modbus register address to start writing at.
            values: Raw register values to write, starting at address.
        """
        ...


def run_tick(plant: PlantModel, io: ModbusIO, dt_s: float, t_sim_s: float) -> PlantOutputs:
    """Read setpoints from the field bus, step the plant, write back outputs.

    Args:
        plant: PlantModel implementation to advance by one step.
        io: Modbus register I/O (real client or in-memory fake).
        dt_s: Timestep length in seconds.
        t_sim_s: Current simulated time, used to derive disturbances.

    Returns:
        The PlantOutputs produced by this step.
    """
    setpoints = {}
    for name, (addr, scale) in WRITE_REGISTERS.items():
        raw = io.read_holding_registers(addr, 1)[0]
        setpoints[name] = raw / scale
    setpoints["y_chg"] = setpoints["y_chg"] / 500.0 - 1.0

    p_it, t_amb = generate_disturbance(t_sim_s)
    t_net_sup, t_net_ret = network_temperatures(t_amb)
    inputs = PlantInputs(
        P_it=p_it,
        T_amb=t_amb,
        T_net_sup=t_net_sup,
        T_net_ret=t_net_ret,
        Q_dem=network_heat_demand(t_amb),
        **setpoints,
    )

    outputs = plant.do_step(dt_s, inputs)

    for name, (addr, scale) in READ_REGISTERS.items():
        value = (
            getattr(outputs, name)
            if hasattr(outputs, name)
            else getattr(inputs, name)
        )
        io.write_registers(addr, [int(round(value * scale))])

    return outputs
