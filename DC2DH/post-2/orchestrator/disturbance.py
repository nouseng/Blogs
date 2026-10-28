"""Deterministic IT-load and outdoor-temperature disturbance
generator.

The IT trace is a 10 MW pod running near flat, with a small ripple
standing in for checkpoint dips. AI training load does not follow the
enterprise diurnal curve the older data-center literature assumes, and
a plant sized against that curve would be sized wrong.

This post deliberately keeps both traces synthetic. Historical and live
feeds belong to the data-integration layer that follows this prototype.
"""

import math

P_IT_BASE_KW = 10000.0
P_IT_AMPLITUDE_KW = 400.0
T_AMB_BASE_C = 7.0
T_AMB_AMPLITUDE_C = 6.0
DAY_S = 86400.0


def generate_disturbance(t_sim_s: float) -> tuple[float, float]:
    """Deterministic stand-in for real IT-load and weather traces.
    This exists so the prototype has repeatable signals moving through
    the loop before live or historical feeds are connected.

    Args:
        t_sim_s: Simulated time in seconds since sim start.

    Returns:
        Tuple of (P_it in kW, T_amb in degC), each a sine wave over a
        24-hour period.
    """
    phase = 2.0 * math.pi * (t_sim_s % DAY_S) / DAY_S
    p_it = P_IT_BASE_KW + P_IT_AMPLITUDE_KW * math.sin(phase)
    t_amb = T_AMB_BASE_C + T_AMB_AMPLITUDE_C * math.sin(phase)
    return p_it, t_amb
