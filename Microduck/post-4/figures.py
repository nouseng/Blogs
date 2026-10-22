"""Redraw the friction figure of Part 4 into images/ and print the numbers quoted in the post."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import *  # noqa: E402,F403

DATA, IMAGES = folders(__file__)
# MuJoCo walks of contact-law.ipynb (walk_mujoco): same policy, 0.3 m/s command, last 4 s of 6 s
MUJOCO = {"0.3": 0.0917, "0.5": 0.1329, "1.0": 0.1323, "2.0": 0.1224}

duck, fall = {}, {}
for mu in MUJOCO:
    df = read(DATA / f"walk_mu{mu.replace('.', '')}.csv")
    fallen = df["trunkHeight"] < 0.09
    fall[mu] = df["time"][fallen].iloc[0] if fallen.any() else None
    duck[mu] = np.nan if fallen.any() else speed(df)
    status = f"falls at {fall[mu]:.2f} s" if fall[mu] else f"{duck[mu]:.3f} m/s"
    print(f"mu {mu}: Duck {status}, MuJoCo {MUJOCO[mu]:.3f} m/s")

x = np.arange(len(MUJOCO))
fig, ax = plt.subplots(figsize=(6.5, 3.6))
ax.bar(x - 0.2, list(duck.values()), 0.38, color=BLUE, label="Duck library")
ax.bar(x + 0.2, list(MUJOCO.values()), 0.38, color=GREY, label="MuJoCo")
for xi, mu in zip(x, MUJOCO):
    if fall[mu]:
        ax.text(xi - 0.2, 0.006, f"falls\nat {fall[mu]:.2f} s", ha="center", va="bottom",
                color="#222", fontsize=9)
    else:
        ax.text(xi - 0.2, duck[mu] + 0.003, f"{duck[mu]:.3f}", ha="center", fontsize=8, color="#222")
    ax.text(xi + 0.2, MUJOCO[mu] + 0.003, f"{MUJOCO[mu]:.3f}", ha="center", fontsize=8, color="#222")
ax.set_xticks(x, [f"μ = {m}" for m in MUJOCO])
ax.set_ylabel("Walking speed, last 4 s [m/s]")
ax.set_ylim(0, 0.18)
ax.set_xlim(-0.65, 3.6)
ax.set_axisbelow(True)
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", ncol=2)
fig.tight_layout()
fig.savefig(IMAGES / "friction_sweep.png")
