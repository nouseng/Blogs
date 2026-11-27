"""Protocol implemented by the physics-backed Modelica FMU adapter."""

from typing import Protocol
from contracts.signals import PlantInputs, PlantOutputs


class PlantModel(Protocol):
    """Anything that can advance plant state by one timestep given setpoints."""

    def do_step(self, dt_s: float, inputs: PlantInputs) -> PlantOutputs:
        """Advance the plant by one timestep.

        Args:
            dt_s: Timestep length in seconds.
            inputs: Setpoints and disturbances for this step.

        Returns:
            Resulting plant outputs at the end of the step.
        """
        ...
