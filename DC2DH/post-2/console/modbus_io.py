"""Console-side Modbus reads and writes for the tile and controls."""

from contracts.signals import READ_REGISTERS, WRITE_REGISTERS
from pymodbus.client import ModbusTcpClient

TILE_SIGNALS = (
    "T_amb",
    "T_tank_top",
    "Q_sold",
    "P_grid",
    "COP_hp",
    "T_net_del",
    "T_net_ret",
)
SIGNED_TILE_SIGNALS = {"T_amb"}

# Water properties for deriving the district-network delivery flow from the
# delivered heat. rho ~ 1000 kg/m3 makes 1 kg/s ~ 1 l/s of water, so the
# volume flow follows directly from Q / (cp * dT).
WATER_CP_KJ_KG_K = 4.18


def _raise_if_error(result, operation: str) -> None:
    """Raise on a real pymodbus error response while allowing test doubles."""
    if result is not None and hasattr(result, "isError") and result.isError():
        raise RuntimeError(f"{operation} failed: {result}")


def read_tile_values(client: ModbusTcpClient) -> dict[str, float]:
    """Read the console tile values from the gateway.

    Args:
        client: Connected ModbusTcpClient pointed at the gateway.

    Returns:
        Dict of tile signal name to engineering-unit value.
    """
    values = {}
    for name in TILE_SIGNALS:
        addr, scale = READ_REGISTERS[name]
        result = client.read_holding_registers(addr, 1)
        _raise_if_error(result, f"reading {name} at address {addr}")
        if not hasattr(result, "registers") or len(result.registers) != 1:
            raise RuntimeError(
                f"reading {name} at address {addr} returned no register"
            )
        raw_value = result.registers[0]
        if name in SIGNED_TILE_SIGNALS and raw_value >= 0x8000:
            raw_value -= 0x10000
        values[name] = raw_value / scale
    return values


def write_q_hp_set(
    client: ModbusTcpClient, value_kw: float
) -> None:
    """Write the heat-pump thermal duty setpoint.

    Args:
        client: Connected ModbusTcpClient pointed at the gateway.
        value_kw: Desired duty in kW, engineering units.
    """
    addr, scale = WRITE_REGISTERS["Q_hp_set"]
    result = client.write_register(addr, int(value_kw * scale))
    _raise_if_error(result, f"writing Q_hp_set at address {addr}")


def write_u_prod(client: ModbusTcpClient, product: int) -> None:
    """Write the delivery product selector.

    Args:
        client: Connected ModbusTcpClient pointed at the gateway.
        product: 0 none, 1 Retur, 2 Inblandning, 3 Prima.
    """
    addr, _ = WRITE_REGISTERS["u_prod"]
    result = client.write_register(addr, int(product))
    _raise_if_error(result, f"writing u_prod at address {addr}")


def write_y_chg(client: ModbusTcpClient, value: float) -> None:
    """Write the accumulator charge/discharge command.

    y_chg spans -1 (discharge) to 1 (charge) in engineering units but
    is carried unsigned on the wire as (value + 1) * 500, per
    contracts/signals.py and the decode in orchestrator/tick.py.

    Args:
        client: Connected ModbusTcpClient pointed at the gateway.
        value: Desired command, -1.0 (discharge) to 1.0 (charge).
    """
    addr, _ = WRITE_REGISTERS["y_chg"]
    result = client.write_register(addr, round((value + 1.0) * 500.0))
    _raise_if_error(result, f"writing y_chg at address {addr}")


def write_y_dry(client: ModbusTcpClient, value: float) -> None:
    """Write the dry-cooler fan duty limit.

    Args:
        client: Connected ModbusTcpClient pointed at the gateway.
        value: Desired duty, 0.0 (fans off) to 1.0 (full duty).
    """
    addr, scale = WRITE_REGISTERS["y_dry"]
    result = client.write_register(addr, int(value * scale))
    _raise_if_error(result, f"writing y_dry at address {addr}")


def network_flow_lps(q_sold_kw: float, t_del_degc: float, t_ret_degc: float) -> float:
    """Derive the district-network water flow from the delivered heat.

    The prototype sells heat, not flow, so there is no flow meter on the
    bus. Flow follows from the heat balance V = Q / (rho * cp * dT) with
    rho ~ 1000 kg/m3, which makes 1 kg/s of water ~ 1 l/s.

    Args:
        q_sold_kw: Heat delivered to the district network, kW.
        t_del_degc: Delivery temperature, degC.
        t_ret_degc: Network return temperature, degC.

    Returns:
        Water volume flow in l/s, or 0.0 when nothing is delivered or the
        delivery has no temperature lift above the return. The model reports
        tNetDel == tNetRet when no delivery is active, so the no-lift guard
        doubles as the no-delivery guard.
    """
    d_t = t_del_degc - t_ret_degc
    if q_sold_kw <= 0.0 or d_t <= 0.0:
        return 0.0
    return q_sold_kw / (WATER_CP_KJ_KG_K * d_t)
