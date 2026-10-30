"""Plot style, data loading and servo constants shared by the figures.py scripts."""
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

if "ipykernel" in sys.modules:
    matplotlib.use("module://matplotlib_inline.backend_inline")
else:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE, ORANGE, GREEN, PINK, GREY = "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#6b6b6b"
# Rhoban/bam bam/params/xl330/m6.json
KT = 0.3459739511711113
RESISTANCE = 2.501880848390462
FRICTION_BASE = 0.011919956825702578
FRICTION_VISCOUS = 0.005788445053875673
JOINTS = ["left hip yaw", "left hip roll", "left hip pitch", "left knee", "left ankle",
          "neck pitch", "head pitch", "head yaw", "head roll",
          "right hip yaw", "right hip roll", "right hip pitch", "right knee", "right ankle"]

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e4e4e4", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#444", "lines.linewidth": 2, "figure.dpi": 150,
                     "legend.frameon": False})


def folders(script):
    here = Path(script).parent
    (here / "images").mkdir(exist_ok=True)
    return here / "data", here / "images"


def read(path):
    return pd.read_csv(path).drop_duplicates("time", keep="last").reset_index(drop=True)


def cols(df, name, n=14):
    return df[[f"{name}[{i}]" for i in range(1, n + 1)]].to_numpy()


def speed(df):
    """Mean forward speed over the last 4 s of the 6 s walk."""
    return (df["distance"].iloc[-1] - np.interp(2, df["time"], df["distance"])) / 4


ROOT = Path(__file__).resolve().parent
MUJOCO = ROOT / "mujoco"
FMU_PLANT = ROOT / "fmu" / "DuckPlant.fmu"
FMU_STAND = ROOT / "fmu" / "DuckStand.fmu"
POLICY = MUJOCO / "velstand.onnx"
# Home pose of the joints, MicroDuck.Components.Robot.q0, in the order of JOINTS
HOME = np.array([0, -0.0873, -0.4579, -0.0049, 0.453, 0.3491, 0.3491, 0, 0, 0, 0.0873, 0.4579, 0.0049, -0.453])
# Policy timing and filters as in MicroDuck.Components.WalkingPolicy and the training environment
PERIOD = 0.02
COMMAND_DELAY = 0.023  # 22.5 ms delay applied at the next 1 ms fixed step, as in OpenModelica
ACTION_SCALE = 0.9
TARGET_FILTER = np.array([0.5 if 5 <= j <= 8 else 0.7 for j in range(14)])
PLANT_OUTPUTS = (["x", "z", "pitch", "batteryCurrent"]
                 + [f"{name}[{i}]" for name in ("gyro", "gravity") for i in range(1, 4)]
                 + [f"{name}[{i}]" for name in ("q", "w", "motorCurrent", "servoTorque") for i in range(1, 15)])


class Plant:
    """DuckPlant.fmu as Model Exchange, integrated with fixed-step fourth-order Runge-Kutta."""

    def __init__(self, parameters):
        from ctypes import POINTER

        from fmpy import extract, read_model_description
        from fmpy.fmi2 import FMU2Model, fmi2Real

        md = read_model_description(str(FMU_PLANT))
        self.vr = {v.name: v.valueReference for v in md.modelVariables}
        self.fmu = FMU2Model(guid=md.guid, unzipDirectory=extract(str(FMU_PLANT)),
                             modelIdentifier=md.modelExchange.modelIdentifier, instanceName="duck")
        self.nx, self.nz = md.numberOfContinuousStates, md.numberOfEventIndicators
        self.x, self.dx, self.z = np.zeros(self.nx), np.zeros(self.nx), np.zeros(self.nz)
        self.px, self.pdx, self.pz = (a.ctypes.data_as(POINTER(fmi2Real)) for a in (self.x, self.dx, self.z))
        self.out_vr = [self.vr[n] for n in PLANT_OUTPUTS]
        self.in_vr = [self.vr[f"qRef[{i}]"] for i in range(1, 15)]
        self.fmu.instantiate()
        self.fmu.setupExperiment(startTime=0)
        if parameters:
            if "supply" in parameters and "kneeSupply" not in parameters:
                parameters = {**parameters, "kneeSupply": parameters["supply"]}
            self.fmu.setReal([self.vr[k] for k in parameters], [float(v) for v in parameters.values()])
        self.q_ref = HOME.copy()
        self.fmu.setReal(self.in_vr, list(HOME))
        self.fmu.enterInitializationMode()
        self.fmu.exitInitializationMode()
        self._event_iteration()
        self.fmu.enterContinuousTimeMode()
        self.t = 0.0
        self.fmu.getContinuousStates(self.px, self.nx)
        self.fmu.getEventIndicators(self.pz, self.nz)

    def _event_iteration(self):
        while True:
            if not self.fmu.newDiscreteStates()[0]:
                break

    def set_targets(self, q_ref):
        self.q_ref = np.array(q_ref)
        self.fmu.setReal(self.in_vr, list(q_ref))

    def outputs(self):
        return np.array(self.fmu.getReal(self.out_vr))

    def _derivatives(self, t, x):
        self.fmu.setTime(t)
        self.x[:] = x
        self.fmu.setContinuousStates(self.px, self.nx)
        self.fmu.getDerivatives(self.pdx, self.nx)
        return self.dx.copy()

    def step(self, h):
        t, x0 = self.t, self.x.copy()
        k1 = self._derivatives(t, x0)
        k2 = self._derivatives(t + h / 2, x0 + h / 2 * k1)
        k3 = self._derivatives(t + h / 2, x0 + h / 2 * k2)
        k4 = self._derivatives(t + h, x0 + h * k3)
        self.t = t + h
        self.fmu.setTime(self.t)
        self.x[:] = x0 + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        self.fmu.setContinuousStates(self.px, self.nx)
        z_old = self.z.copy()
        self.fmu.getEventIndicators(self.pz, self.nz)
        step_event, _ = self.fmu.completedIntegratorStep()
        if step_event or np.any(np.sign(z_old) != np.sign(self.z)):
            # events are handled at the step end, as the fixed-step solvers of OpenModelica do
            self.fmu.enterEventMode()
            self._event_iteration()
            self.fmu.enterContinuousTimeMode()
            self.fmu.getContinuousStates(self.px, self.nx)
            self.fmu.getEventIndicators(self.pz, self.nz)

    def advance(self, t_end, max_step, record):
        n = max(1, int(np.ceil((t_end - self.t) / max_step - 1e-9)))
        h = (t_end - self.t) / n
        for _ in range(n):
            self.step(h)
            record.append([self.t, *self.outputs(), *self.q_ref])

    def close(self):
        self.fmu.terminate()
        self.fmu.freeInstance()


def walk_fmu(speed_command=0.3, duration=6.0, max_step=0.001, command_delay=COMMAND_DELAY, **parameters):
    """Walk the Modelica plant under velstand.onnx, run here in Python at 50 Hz.

    Parameters of DuckPlant.fmu: supply, friction, kneeSupply, kneeBacklash, kneeGain.
    Each target reaches the servos command_delay after its control step, and the network sees the
    joint speeds of the step before, as in training. OpenModelica's fixed-step solver applied the
    22.5 ms delay at the next 1 ms step, so command_delay=0.023 reproduces the runs of the posts.
    """
    import onnxruntime as ort
    from fmpy.fmi2 import FMICallException

    session = ort.InferenceSession(str(POLICY))
    plant = Plant(parameters)
    index = {name: k for k, name in enumerate(PLANT_OUTPUTS)}
    twist = np.zeros(13)
    twist[0] = speed_command
    action, previous_speed, target = np.zeros(14), np.zeros(14), None
    pending = []  # (time the target reaches the servos, target)
    record = [[0.0, *plant.outputs(), *HOME]]
    for k in range(round(duration / PERIOD)):
        t_k = k * PERIOD
        y = plant.outputs()
        gyro = y[[index[f"gyro[{i}]"] for i in range(1, 4)]]
        gravity = y[[index[f"gravity[{i}]"] for i in range(1, 4)]]
        q = y[[index[f"q[{i}]"] for i in range(1, 15)]]
        w = y[[index[f"w[{i}]"] for i in range(1, 15)]]
        obs = np.concatenate([gyro, gravity, q - HOME, previous_speed, action, twist]).astype(np.float32)
        previous_speed = w
        action = session.run(None, {"obs": obs[None]})[0][0].astype(float)
        new = HOME + ACTION_SCALE * action
        target = new if target is None else TARGET_FILTER * new + (1 - TARGET_FILTER) * target
        pending.append((t_k + command_delay, target.copy()))
        t_next = t_k + PERIOD
        try:
            while pending and pending[0][0] < t_next - 1e-12:
                t_apply, q_ref = pending.pop(0)
                plant.advance(t_apply, max_step, record)
                plant.set_targets(q_ref)
            plant.advance(t_next, max_step, record)
            diverged = not abs(record[-1][2]) < 0.5
        except FMICallException:
            diverged = True
        if diverged:
            # only the soles collide, so a fallen robot sinks through the floor until the solution
            # breaks down near a trunk pitch of 90 deg, where the Cardan angles are singular
            print(f"Stopped at t = {plant.t:.2f} s: the robot has fallen and the solution diverges")
            break
    plant.close()
    record = [r for r in record if abs(r[2]) < 0.5]
    df = pd.DataFrame(record, columns=["time"] + PLANT_OUTPUTS + [f"qRef[{i}]" for i in range(1, 15)])
    return df.rename(columns={"x": "distance", "z": "trunkHeight", "pitch": "trunkPitch"})


def stand_fmu(gain=800, stop_time=1.0):
    """Hold the home pose at a servo gain register value with DuckStand.fmu (CVODE)."""
    from fmpy import simulate_fmu

    outputs = ["z", "pitch", "leftLoad", "rightLoad"]
    result = simulate_fmu(str(FMU_STAND), fmi_type="ModelExchange", solver="CVode", relative_tolerance=1e-6,
                          stop_time=stop_time, output_interval=0.002, start_values={"gain": gain}, output=outputs)
    df = pd.DataFrame({name: result[name] for name in result.dtype.names})
    return df.rename(columns={"z": "trunkHeight", "pitch": "trunkPitch"})


def stand_mujoco(gain=800, duration=1.0):
    """Drop the MuJoCo robot from the STAND keyframe (2.8 mm) with the servos holding the home pose."""
    import mujoco

    ns = mujoco_walk()
    model, data, qadr, dadr = ns["load"](ns["SCENE"])
    model.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_ACTUATION
    model.dof_armature[dadr] = ns["ARMATURE"]
    model.dof_damping[dadr] = FRICTION_VISCOUS
    model.dof_frictionloss[dadr] = FRICTION_BASE
    mujoco.mj_setConst(model, data)
    mujoco.mj_resetDataKeyframe(model, data, model.key("STAND").id)
    target = data.qpos[qadr].copy()
    floor = model.geom("floor").id
    rows, force = [(0.0, float(data.qpos[2]), 0.0, 0.0)], np.zeros(6)
    for step in range(int(duration / model.opt.timestep)):
        ns["servo_force"](model, data, qadr, dadr, target, gain)
        mujoco.mj_step(model, data)
        if step % 10 == 0 or data.time < 0.2:
            normal = np.zeros(2)
            for i in range(data.ncon):
                con = data.contact[i]
                if floor in (con.geom1, con.geom2):
                    mujoco.mj_contactForce(model, data, i, force)
                    other = con.geom1 if con.geom2 == floor else con.geom2
                    normal[0 if "left" in model.geom(other).name else 1] += force[0]
            rows.append((data.time, data.qpos[2], normal[0], normal[1]))
    return pd.DataFrame(rows, columns=["time", "trunkHeight", "leftLoad", "rightLoad"])


def mujoco_walk():
    """Load the MuJoCo walk of mujoco/walk.ipynb (model, BAM servo, policy loop) as a namespace."""
    import contextlib
    import io
    import json

    nb = json.loads((MUJOCO / "walk.ipynb").read_text(encoding="utf-8"))
    namespace = {}
    for cell in nb["cells"]:
        source = "".join(cell["source"])
        if cell["cell_type"] == "code" and source.startswith(("from pathlib", "def load", "# bam/", "PERIOD")):
            with contextlib.redirect_stdout(io.StringIO()):  # the cells print model summaries
                cleaned = source.replace("from IPython.display import Video", "").replace("import imageio", "")
                exec(cleaned, namespace)  # noqa: S102
            namespace["SCENE"] = str(MUJOCO / "model" / "scene_backlash.xml")
            namespace["ONNX"] = str(MUJOCO / "velstand.onnx")
    return namespace


def walk_mujoco(speed_command=0.3, duration=6.0, friction=None):
    """Walk the MuJoCo robot, optionally with every geom's friction coefficient replaced."""
    ns = mujoco_walk()
    if friction is not None:
        load = ns["load"]

        def load_with_friction(scene):
            model, data, qadr, dadr = load(scene)
            model.geom_friction[:, 0] = friction
            return model, data, qadr, dadr

        ns["load"] = load_with_friction
    rows = ns["run"](ns["SCENE"], ns["ONNX"], speed_command, duration)
    return pd.DataFrame({"time": [r["t"] for r in rows], "distance": [r["pos"][0] for r in rows],
                         "trunkHeight": [r["pos"][2] for r in rows], "trunkPitch": [r["pitch"] for r in rows]})
