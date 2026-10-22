"""Redraw the figures of Part 2 into images/ and print the numbers quoted in the post."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import *  # noqa: E402,F403

DATA, IMAGES = folders(__file__)

walk = read(DATA / "walk_nominal.csv")
late = (walk["time"] >= 2).to_numpy()
t = walk["time"].to_numpy()
q, q_ref, tau = cols(walk, "robot.q"), cols(walk, "robot.qRef"), cols(walk, "servoTorque")
w = np.gradient(q, t, axis=0)

fig, ax = plt.subplots(figsize=(6.5, 4.0))
ax.scatter(np.abs(w[late]).ravel(), np.abs(tau[late]).ravel(), s=2, color=GREY, alpha=0.15, lw=0)
ax.text(0.4, 0.31, "Walking, all 14 joints", color="#222")
ws = np.linspace(0, 25, 200)
for v, c in [(8.2, BLUE), (7.4, GREEN), (6.5, ORANGE)]:
    limit = KT * (v - KT * ws) / RESISTANCE - FRICTION_BASE - FRICTION_VISCOUS * ws
    ax.plot(ws, np.clip(limit, 0, None), color=c)
    w0 = (KT * v / RESISTANCE - FRICTION_BASE) / (KT ** 2 / RESISTANCE + FRICTION_VISCOUS)
    ax.annotate(f"{v} V", (w0, 0), xytext=(-2, 8), textcoords="offset points", color="#222")
    print(f"{v} V: stall {KT * v / RESISTANCE - FRICTION_BASE:.2f} N.m, no-load speed {w0:.1f} rad/s")
ax.set_xlabel("Joint speed [rad/s]")
ax.set_ylabel("Joint torque [N·m]")
ax.set_xlim(0, 25)
ax.set_ylim(0, 1.15)
fig.tight_layout()
fig.savefig(IMAGES / "torque_speed.png")

mujoco = read(DATA / "mujoco_standing.csv")
fig, ax = plt.subplots(figsize=(6.5, 3.6))
for g, c in [("800", BLUE), ("200", ORANGE)]:
    stand = read(DATA / f"stand_gain{g}.csv")
    ax.plot(stand["time"], 1e3 * stand["trunkHeight"], color=c, label=f"Gain {g}, Duck library")
    ax.plot(mujoco["time"], 1e3 * mujoco[f"trunkHeight_gain{g}"], color=c, ls="--", lw=1.5,
            label=f"Gain {g}, MuJoCo")
    for name, z, tz in [("Duck", stand["trunkHeight"], stand["time"]),
                        ("MuJoCo", mujoco[f"trunkHeight_gain{g}"], mujoco["time"])]:
        below = z < 0.1
        when = f"{tz[below].iloc[0]:.2f} s" if below.any() else "never"
        print(f"gain {g} {name}: final height {1e3 * z.iloc[-1]:.1f} mm, below 100 mm {when}")
ax.set_ylim(40, 125)
ax.set_xlim(0, 3)
ax.set_xlabel("Time [s]")
ax.set_ylabel("Trunk height [mm]")
ax.legend(loc="lower left", ncol=2, fontsize=9)
fig.tight_layout()
fig.savefig(IMAGES / "standing_gain.png")

error = np.degrees(q_ref - q)[late]
for j in (3, 12):
    print(f"{JOINTS[j]}: tracking error RMS {np.sqrt((error[:, j] ** 2).mean()):.1f} deg, "
          f"mean {error[:, j].mean():.1f} deg")
peak_tau, peak_w = np.abs(tau[late]).max(0), np.abs(w[late]).max(0)
print(f"peak torque {peak_tau.max():.3f} N.m ({JOINTS[peak_tau.argmax()]}), "
      f"peak speed {peak_w.max():.2f} rad/s ({JOINTS[peak_w.argmax()]})")
gain = 200 * (4096 / (2 * np.pi)) / (256 * 885)
print(f"error gain {gain:.3f} 1/rad, stiffness {gain * 7.4 * KT / RESISTANCE:.3f} N.m/rad at 7.4 V, "
      f"back-EMF damping {KT ** 2 / RESISTANCE:.4f} N.m.s/rad")
