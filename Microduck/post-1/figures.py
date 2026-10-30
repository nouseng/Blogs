"""Redraw the figures of Part 1 into images/ and print the numbers quoted in the post.

The walk GIF and its still frame are rendered from the MuJoCo walk; the comparison plot uses the
archived OpenModelica walk in data/walk_duck.csv and the MuJoCo walk, saved to data/walk_mujoco.csv.
The knee tracking and copper-heating shift plots are simulated live from fmu/DuckPlant.fmu.
"""
import mujoco
from PIL import Image

from common import *  # noqa: F403

DATA, IMAGES = folders(__file__)
WIDTH, HEIGHT = 960, 540
GIF_WIDTH, FRAME_STRIDE = 600, 4  # 50 Hz control steps, every 4th frame: 12.5 fps

ns = mujoco_walk()
render_model = mujoco.MjModel.from_xml_path(ns["SCENE"])
render_model.vis.global_.offwidth, render_model.vis.global_.offheight = WIDTH, HEIGHT
renderer = mujoco.Renderer(render_model, HEIGHT, WIDTH)
camera = mujoco.MjvCamera()
camera.distance, camera.azimuth, camera.elevation = 0.6, 140, -15
frames = []


def grab(data):
    camera.lookat[:] = data.qpos[:3]
    renderer.update_scene(data, camera)
    frames.append(renderer.render())


rows = ns["run"](ns["SCENE"], ns["ONNX"], 0.3, 6.0, on_tick=grab)
renderer.close()
Image.fromarray(frames[len(frames) // 2]).save(IMAGES / "walk-frame.png")
small = [Image.fromarray(f).resize((GIF_WIDTH, GIF_WIDTH * HEIGHT // WIDTH), Image.LANCZOS).quantize(64)
         for f in frames[::FRAME_STRIDE]]
small[0].save(IMAGES / "walk.gif", save_all=True, append_images=small[1:], duration=80, loop=0, optimize=True)

mj = pd.DataFrame({"time": [r["t"] for r in rows], "distance": [r["pos"][0] for r in rows],
                   "trunkHeight": [r["pos"][2] for r in rows]})
mj.to_csv(DATA / "walk_mujoco.csv", index=False)
duck = read(DATA / "walk_duck.csv")

fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 4.3), sharex=True)
a1.plot(duck["time"], duck["distance"], color=BLUE, label="MicroDuck library")
a1.plot(mj["time"], mj["distance"], color=GREY, ls="--", lw=1.5, label="MuJoCo")
a2.plot(duck["time"], 1e3 * duck["trunkHeight"], color=BLUE)
a2.plot(mj["time"], 1e3 * mj["trunkHeight"], color=GREY, ls="--", lw=1.5)
a1.set_ylabel("Forward position [m]")
a1.legend(loc="upper left")
a2.set_ylabel("Trunk height [mm]")
a2.set_xlabel("Time [s]")
fig.tight_layout()
fig.savefig(IMAGES / "walking.png")

for name, df in (("MicroDuck library", duck), ("MuJoCo", mj)):
    print(f"{name}: {speed(df):.3f} m/s over the last 4 s, {df['distance'].iloc[-1]:.3f} m after 6 s")

# FMU runs for knee tracking and copper-heating shift
fmu_nom = walk_fmu()
fmu_limp = walk_fmu(kneeGain=0)

t = fmu_nom["time"].to_numpy()
win = (t >= 2.0) & (t <= 4.0)
q_deg = np.degrees(cols(fmu_nom, "q"))
qref_deg = np.degrees(cols(fmu_nom, "qRef"))
tau = cols(fmu_nom, "servoTorque")

fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 4.1), sharex=True)
a1.plot(t[win], qref_deg[win, 3], color=ORANGE, ls="--", lw=1.6, label="Target $q_{\\mathrm{ref}}$")
a1.plot(t[win], q_deg[win, 3], color=BLUE, label="Measured $q$")
a1.set_ylim(-38, 62)
a1.set_ylabel("Left knee angle [deg]")
a1.legend(loc="upper right", ncol=2)
a2.plot(t[win], tau[win, 3], color=BLUE)
a2.set_ylabel("Servo torque [N·m]")
a2.set_xlabel("Time [s]")
fig.tight_layout()
fig.savefig(IMAGES / "knee_tracking.png")

late = t >= 2.0
cu_nom = (RESISTANCE * cols(fmu_nom, "motorCurrent")[late] ** 2).mean(0)
cu_limp = (RESISTANCE * cols(fmu_limp, "motorCurrent")[fmu_limp["time"] >= 2.0] ** 2).mean(0)
leg_idx = [0, 1, 2, 3, 4, 9, 10, 11, 12, 13]
labels = ["L yaw", "L roll", "L pitch", "L knee", "L ankle",
          "R yaw", "R roll", "R pitch", "R knee", "R ankle"]
x_pos = np.arange(len(leg_idx))
w_bar = 0.36

fig, ax = plt.subplots(figsize=(6.5, 3.2))
ax.bar(x_pos - w_bar / 2, cu_nom[leg_idx], w_bar, color=BLUE, label="Nominal (7.4 V)")
ax.bar(x_pos + w_bar / 2, cu_limp[leg_idx], w_bar, color=ORANGE, label="Unpowered left knee (kneeGain=0)")
ax.set_xticks(x_pos, labels, rotation=25, ha="right")
ax.set_ylabel("Mean copper loss $Ri^2$ [W]")
ax.legend(loc="upper left")
fig.tight_layout()
fig.savefig(IMAGES / "copper_shift.png")
