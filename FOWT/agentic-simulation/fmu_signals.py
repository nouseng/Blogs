"""FMU signal name mapping for the shipped FOWT co-simulation FMU.

These names are specific to the Modelica model this FMU was exported
from. They live in this small module so the physics in ``simulation.py``
stays independent of the FMU's internal variable naming.
"""

MOTION_OUTPUTS = ("surge", "sway", "heave", "roll", "pitch", "yaw")

MOORING_FORCE_INPUTS = tuple(
    f"forceML{i}[{j}]" for i in (1, 2, 3) for j in (1, 2, 3)
)

WAVE_FORCE_INPUTS = ("waveForces[1]", "waveForces[2]", "waveForces[3]")
WAVE_MOMENT_INPUTS = ("waveMoments[1]", "waveMoments[2]", "waveMoments[3]")

WIND_SPEED_INPUT = "windSpeed"
PITCH_COLLECTIVE_INPUT = "pitchCollective"


def pack_line_force(fx: float, fy: float, fz: float) -> list[float]:
    """Reorder an earth-frame line force into the FMU's mooring input slot layout."""
    return [fx, fz, fy]
