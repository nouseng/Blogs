"""Redraw the figures of Part 1 into images/ and print the numbers quoted in the post.

The walk GIF and its still frame are rendered from the MuJoCo walk; the comparison plot uses the
archived OpenModelica walk in data/walk_duck.csv and the MuJoCo walk, saved to data/walk_mujoco.csv.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import *  # noqa: E402,F403

import mujoco  # noqa: E402
from PIL import Image  # noqa: E402

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
a1.plot(duck["time"], duck["distance"], color=BLUE, label="Duck library")
a1.plot(mj["time"], mj["distance"], color=GREY, ls="--", lw=1.5, label="MuJoCo")
a2.plot(duck["time"], 1e3 * duck["trunkHeight"], color=BLUE)
a2.plot(mj["time"], 1e3 * mj["trunkHeight"], color=GREY, ls="--", lw=1.5)
a1.set_ylabel("Forward position [m]")
a1.legend(loc="upper left")
a2.set_ylabel("Trunk height [mm]")
a2.set_xlabel("Time [s]")
fig.tight_layout()
fig.savefig(IMAGES / "walking.png")

for name, df in (("Duck library", duck), ("MuJoCo", mj)):
    print(f"{name}: {speed(df):.3f} m/s over the last 4 s, {df['distance'].iloc[-1]:.3f} m after 6 s")
