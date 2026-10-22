"""Redraw the figure of Part 3 into images/ and print the numbers quoted in the post."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import *  # noqa: E402,F403

DATA, IMAGES = folders(__file__)
WINDOW = 200  # samples of 1 ms, the 0.2 s moving average

fig, (a1, a2) = plt.subplots(2, 1, figsize=(6.5, 5.0), sharex=True)
for v, c, ls in [("82", BLUE, "-"), ("74", GREEN, "-."), ("65", ORANGE, "--")]:
    df = read(DATA / f"walk_{v}V.csv")
    t, i = df["time"].to_numpy(), df["batteryCurrent"].to_numpy()
    volts = int(v) / 10
    mean = np.convolve(i, np.ones(WINDOW) / WINDOW, mode="same")
    a1.plot(t, df["distance"], color=c, ls=ls, label=f"{volts} V")
    a2.plot(t, i, color=c, lw=0.6, alpha=0.35)
    a2.plot(t[WINDOW:-WINDOW], mean[WINDOW:-WINDOW], color=c, ls=ls)
    late, settled = t >= 2, (t > 1) & (t < 5.8)
    print(f"{volts} V: speed {speed(df):.3f} m/s, distance {df['distance'].iloc[-1]:.3f} m, "
          f"mean current {i[late].mean():.3f} A, mean power {volts * i[late].mean():.2f} W, "
          f"peak {i.max():.2f} A at {t[i.argmax()]:.2f} s, "
          f"0.2 s average {mean[settled].min():.2f} to {mean[settled].max():.2f} A")
a1.set_ylabel("Forward position [m]")
a1.legend(loc="upper left")
a2.set_ylabel("Servo supply current [A]")
a2.set_xlabel("Time [s]")
fig.tight_layout()
fig.savefig(IMAGES / "voltage_sweep.png")

gain = 200 * (4096 / (2 * np.pi)) / (256 * 885)
for v in (8.2, 7.4, 6.5):
    print(f"servo stiffness at {v} V: {gain * v * KT / RESISTANCE:.3f} N.m/rad")
