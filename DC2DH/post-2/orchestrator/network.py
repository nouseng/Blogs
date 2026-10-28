"""District-heating supply and return temperatures vs outdoor
temperature.

Digitised from Energiforsk 2024:1059, "Handbok for sankta
fjarrvarmetemperaturer", Figure 5. That figure is a Swedish sector
average drawn from the FVB database covering 213 district heating
systems and over 85 percent of annual deliveries. It is not a
Stockholm measurement, and anything published from it must say so.

Stockholm Exergi does not publish its own network temperatures. Its
stated Prima delivery range of 68 to 103 degC sits on this curve,
which is corroboration, not confirmation.
"""

T_BREAKPOINT_C = 0.0
T_SUP_FLAT_C = 75.0
T_SUP_COLD_C = 110.0
T_AMB_COLD_C = -20.0
T_RET_COLD_C = 59.0
T_RET_MIN_C = 40.5
T_AMB_RET_MIN_C = 12.0
T_RET_WARM_SLOPE = 0.35


Q_DEM_BASE_KW = 2000.0
Q_DEM_SLOPE_KW_PER_K = 900.0
T_DEM_BALANCE_C = 17.0
Q_DEM_MAX_KW = 20000.0


def network_heat_demand(t_amb: float) -> float:
    """Heat this connection's branch of the network will take, kW.

    A degree-day profile: a flat summer base standing in for domestic hot
    water and distribution losses, plus a space-heating term proportional to
    how far the outdoor temperature sits below the balance point, capped at
    the branch's hydraulic limit.

    Every constant here is CHOSEN, not sourced. Stockholm Exergi publishes
    neither branch-level demand nor what it will buy hour by hour, and the
    binding limit on a real connection is commercial rather than physical.
    The shape is standard practice; the scale is illustrative, and it sets
    how much of the pod's output can be sold, so treat any recovery figure
    computed from it as conditional on this curve.

    Args:
        t_amb: Outdoor dry-bulb temperature, degC.

    Returns:
        Heat demand in kW.
    """
    heating = max(0.0, T_DEM_BALANCE_C - t_amb) * Q_DEM_SLOPE_KW_PER_K
    return min(Q_DEM_MAX_KW, Q_DEM_BASE_KW + heating)


def network_temperatures(t_amb: float) -> tuple[float, float]:
    """Return the network supply and return temperatures.

    Args:
        t_amb: Outdoor dry-bulb temperature, degC.

    Returns:
        Tuple of (supply degC, return degC).
    """
    if t_amb <= T_AMB_COLD_C:
        t_sup = T_SUP_COLD_C
    elif t_amb >= T_BREAKPOINT_C:
        t_sup = T_SUP_FLAT_C
    else:
        frac = (T_BREAKPOINT_C - t_amb) / (
            T_BREAKPOINT_C - T_AMB_COLD_C
        )
        t_sup = T_SUP_FLAT_C + frac * (T_SUP_COLD_C - T_SUP_FLAT_C)

    if t_amb <= T_AMB_COLD_C:
        t_ret = T_RET_COLD_C
    elif t_amb <= T_AMB_RET_MIN_C:
        frac = (T_AMB_RET_MIN_C - t_amb) / (
            T_AMB_RET_MIN_C - T_AMB_COLD_C
        )
        t_ret = T_RET_MIN_C + frac * (T_RET_COLD_C - T_RET_MIN_C)
    else:
        t_ret = T_RET_MIN_C + T_RET_WARM_SLOPE * (
            t_amb - T_AMB_RET_MIN_C
        )

    return t_sup, t_ret
