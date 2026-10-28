"""Wire contract: PlantModel signal dataclasses and the Modbus map."""

from dataclasses import dataclass


@dataclass
class PlantInputs:
    """Setpoints and disturbances fed into a PlantModel.do_step call.

    Attributes:
        P_it: IT electrical load, kW.
        T_amb: Outdoor dry-bulb temperature, degC.
        T_net_sup: Network required supply temperature, degC.
        T_net_ret: Network incoming return temperature, degC.
        u_prod: Delivery product. 0 none, 1 Retur, 2 Inblandning,
            3 Prima.
        Q_hp_set: Heat-pump thermal duty setpoint, kW.
        y_dry: Dry-cooler duty, 0 to 1.
        y_chg: Accumulator command, -1 discharge to 1 charge.
        Q_dem: Heat the network will take from this connection, kW.
    """

    P_it: float
    T_amb: float
    T_net_sup: float
    T_net_ret: float
    u_prod: float
    Q_hp_set: float
    y_dry: float
    y_chg: float
    Q_dem: float


@dataclass
class PlantOutputs:
    """Results of a PlantModel.do_step call.

    Attributes:
        Q_hall: Heat rejected by the data hall, kW.
        Q_sold: Heat delivered to the district network, kW.
        Q_dump: Heat rejected to ambient, kW.
        P_hp: Heat-pump electrical power, kW.
        P_dry: Dry-cooler fan power, kW.
        P_air: Air-fraction cooling power, kW.
        P_grid: Grid import, kW. Never negative: nothing exports.
        T_tank_top: Accumulator top node temperature, degC.
        T_tank_bot: Accumulator bottom node temperature, degC.
        T_liq_sup: Liquid loop supply temperature, degC.
        T_liq_ret: Liquid loop return temperature, degC.
        COP_hp: Heat-pump COP. 0.0 when no lift was used.
        T_net_del: Temperature actually delivered to the district
            network, degC. Defaults to 0.0 for PlantModel
            implementations that do not compute it separately.
    """

    Q_hall: float
    Q_sold: float
    Q_dump: float
    P_hp: float
    P_dry: float
    P_air: float
    P_grid: float
    T_tank_top: float
    T_tank_bot: float
    T_liq_sup: float
    T_liq_ret: float
    COP_hp: float
    T_net_del: float = 0.0


# name -> (zero-based Modbus address, scale). Address = register - 40001.
# kW signals use scale 1.0: a 10 MW pod at scale 10 would need 100000,
# and a Modbus holding register tops out at 65535. Temperatures keep
# 0.01 K resolution; 1 kW resolution is noise at this size.
READ_REGISTERS: dict[str, tuple[int, float]] = {
    "Q_hall": (0, 1.0),
    "Q_sold": (1, 1.0),
    "Q_dump": (2, 1.0),
    "P_hp": (3, 1.0),
    "P_dry": (4, 1.0),
    "P_air": (5, 1.0),
    "P_grid": (6, 1.0),
    "T_tank_top": (7, 100.0),
    "T_tank_bot": (8, 100.0),
    "T_liq_sup": (9, 100.0),
    "T_liq_ret": (10, 100.0),
    "COP_hp": (11, 100.0),
    "P_it": (12, 1.0),
    "T_amb": (13, 100.0),
    "T_net_sup": (14, 100.0),
    "T_net_ret": (15, 100.0),
    "T_net_del": (16, 100.0),
    "Q_dem": (17, 1.0),
}

WRITE_REGISTERS: dict[str, tuple[int, float]] = {
    "u_prod": (100, 1.0),
    "Q_hp_set": (101, 1.0),
    "y_dry": (102, 1000.0),
    "y_chg": (103, 1.0),
}

# Clamp bounds in ENGINEERING units. gateway/registers.py multiplies
# each bound by its scale to get the raw limit, so y_dry's (0.0, 1.0)
# becomes 0..1000 raw at scale 1000.
# y_chg carries -1..1 as 0..1000; see orchestrator/tick.py for the
# decode. This keeps T_amb the only signed value on the bus.
WRITE_BOUNDS: dict[str, tuple[float, float]] = {
    "u_prod": (0.0, 3.0),
    "Q_hp_set": (0.0, 8000.0),
    "y_dry": (0.0, 1.0),
    "y_chg": (0.0, 1000.0),
}
