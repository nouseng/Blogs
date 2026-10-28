"""PlantModel implementation over the StockholmPod FMU (fmpy)."""

import os
import zipfile
from pathlib import Path

from fmpy import extract, platform as fmpy_platform, read_model_description
from fmpy.fmi2 import FMU2Slave
from fmpy.util import compile_platform_binary

from contracts.signals import PlantInputs, PlantOutputs

DEFAULT_FMU_PATH = (
    Path(__file__).resolve().parent.parent
    / "modelica" / "DataCenterHeatRecovery" / "StockholmPod.fmu"
)

# contracts/signals.py name -> StockholmPod.mo variable name.
_INPUT_NAMES = {
    "P_it": "pIt",
    "T_amb": "tAmb",
    "T_net_sup": "tNetSup",
    "T_net_ret": "tNetRet",
    "u_prod": "uProd",
    "Q_hp_set": "qHpSet",
    "y_dry": "yDry",
    "y_chg": "yChg",
    "Q_dem": "qDem",
}
_OUTPUT_NAMES = {
    "Q_hall": "qHall",
    "Q_sold": "qSold",
    "Q_dump": "qDump",
    "P_hp": "pHp",
    "P_dry": "pDry",
    "P_air": "pAir",
    "P_grid": "pGrid",
    "T_tank_top": "tTankTop",
    "T_tank_bot": "tTankBot",
    "T_liq_sup": "tLiqSup",
    "T_liq_ret": "tLiqRet",
    "COP_hp": "copHp",
    "T_net_del": "tNetDel",
}


def _has_platform_binary(fmu_path: str) -> bool:
    """Check whether fmu_path already carries a compiled binary for this platform."""
    with zipfile.ZipFile(fmu_path) as archive:
        prefix = f"binaries/{fmpy_platform}/"
        return any(name.startswith(prefix) for name in archive.namelist())


class FMUPlantModel:
    """StockholmPod FMU driven through fmpy, behind the PlantModel protocol.

    The committed FMU ships prebuilt binaries for both targets: win64
    (Windows dev/tests) and linux64 (the slim container), each with
    CVODE and its SUNDIALS 5.4 libs alongside (rpath $ORIGIN). fmpy
    loads the matching one directly, so there is no runtime compile on
    either platform. The _has_platform_binary/compile_platform_binary
    guard below is only a fallback for an unshipped platform, and would
    need a C toolchain the container deliberately omits.

    The committed FMU embeds CVODE (adaptive implicit BDF) as its
    co-simulation solver -- resources/StockholmPod_flags.json carries
    {"s": "cvode"}, and modelDescription declares
    canHandleVariableCommunicationStepSize. Each fmi2DoStep may therefore
    take adaptive internal steps to hold tolerance, so the adapter hands it
    whole communication steps while CVODE controls the integration.

    CON-29 originally sub-stepped each tick at 0.1 s to stabilise the plant
    loop against a fixed-step explicit-Euler export. The CVODE rebuild removes
    that known restriction at the tested 30 s communication step, so the
    adapter now makes one fmi2DoStep call per tick. The communication step still
    sets the inputs' zero-order hold and the outputs' sampling interval; this is
    not a claim that arbitrarily large communication steps stay accurate.
    """

    def __init__(self, fmu_path: os.PathLike | str = DEFAULT_FMU_PATH) -> None:
        """Args:
            fmu_path: Path to the StockholmPod FMU.
        """
        fmu_path = str(fmu_path)
        if not _has_platform_binary(fmu_path):
            compile_platform_binary(fmu_path)

        model_description = read_model_description(fmu_path)
        self._value_refs = {
            v.name: v.valueReference for v in model_description.modelVariables
        }
        unzipdir = extract(fmu_path)
        self._fmu = FMU2Slave(
            guid=model_description.guid,
            unzipDirectory=unzipdir,
            modelIdentifier=model_description.coSimulation.modelIdentifier,
            instanceName="StockholmPod",
        )
        self._fmu.instantiate()
        self._fmu.setupExperiment(startTime=0.0)
        self._fmu.enterInitializationMode()
        self._fmu.exitInitializationMode()
        self._t_s = 0.0

    def do_step(self, dt_s: float, inputs: PlantInputs) -> PlantOutputs:
        """Advance the FMU by one co-simulation step.

        Args:
            dt_s: Timestep length in seconds.
            inputs: Setpoints and disturbances for this step.

        Returns:
            Resulting plant outputs at the end of the step.
        """
        in_vrs = [self._value_refs[mo_name] for mo_name in _INPUT_NAMES.values()]
        in_vals = [float(getattr(inputs, name)) for name in _INPUT_NAMES]
        self._fmu.setReal(in_vrs, in_vals)
        self._fmu.doStep(
            currentCommunicationPoint=self._t_s, communicationStepSize=dt_s
        )
        self._t_s += dt_s

        out_vrs = [self._value_refs[mo_name] for mo_name in _OUTPUT_NAMES.values()]
        out_vals = self._fmu.getReal(out_vrs)
        return PlantOutputs(**dict(zip(_OUTPUT_NAMES, out_vals)))
