"""Redraw the figures of Part 5 into images/ and print the numbers quoted in the post."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import *  # noqa: E402,F403

DATA, IMAGES = folders(__file__)
CASES = [("nominal", "Healthy", BLUE, "-"), ("wornknee", "Left knee, 6° play", GREEN, "-."),
         ("weakknee", "Left knee at 3.7 V", ORANGE, "--"), ("limpknee", "Left knee unpowered", PINK, ":")]


def copper_loss(df):
    """Mean R i^2 of each servo over the last 4 s."""
    late = df["time"] >= 2
    return (RESISTANCE * cols(df, "motorCurrent")[late] ** 2).mean(0)


runs = {name: read(DATA / f"walk_{name}.csv") for name, *_ in CASES}
fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 5.0), sharex=True)
for name, label, c, ls in CASES:
    df = runs[name]
    a1.plot(df["time"], df["distance"], color=c, ls=ls, label=label)
    a2.plot(df["time"], 1e3 * df["trunkHeight"], color=c, ls=ls, lw=1.5)
    fallen = df["trunkHeight"] < 0.09
    if fallen.any():
        print(f"{label}: trunk below 90 mm at {df['time'][fallen].iloc[0]:.2f} s")
        continue
    loss = copper_loss(df)
    late = df["time"] >= 2
    error = np.degrees(df["robot.qRef[4]"] - df["robot.q[4]"])[late]
    print(f"{label}: speed {speed(df):.3f} m/s, distance {df['distance'].iloc[-1]:.3f} m, "
          f"lowest trunk {1e3 * df['trunkHeight'].min():.1f} mm, copper loss {loss.sum():.2f} W "
          f"(left knee {loss[3]:.3f}, right knee {loss[12]:.3f}, hip rolls {loss[1] + loss[10]:.3f}, "
          f"right hip pitch {loss[11]:.3f} W), left knee error RMS {np.sqrt((error ** 2).mean()):.1f} deg")
a1.set_ylabel("Forward position [m]")
a1.legend(loc="upper left", ncol=2)
a2.set_ylabel("Trunk height [mm]")
a2.set_ylim(60, 130)
a2.set_xlabel("Time [s]")
fig.tight_layout()
fig.savefig(IMAGES / "faults.png")

healthy = copper_loss(runs["nominal"])
order = np.argsort(-healthy)
y = np.arange(14)
fig, ax = plt.subplots(figsize=(6.5, 4.2))
for k, (name, label, c) in enumerate([("nominal", "Healthy", BLUE), ("weakknee", "Left knee at 3.7 V", ORANGE)]):
    ax.barh(y + (k - 0.5) * 0.38, copper_loss(runs[name])[order], height=0.36, color=c, label=label)
ax.set_yticks(y, [JOINTS[i] for i in order])
ax.invert_yaxis()
ax.set_xlabel("Mean copper loss [W]")
ax.grid(axis="y", visible=False)
ax.legend(loc="lower right")
fig.tight_layout()
fig.savefig(IMAGES / "copper_loss.png")
