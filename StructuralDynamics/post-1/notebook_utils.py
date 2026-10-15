"""Notebook helpers and reproduction commands for the isolation-spectrum blog."""

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares
from scipy.signal import StateSpace, find_peaks, lsim

HERE = Path(__file__).resolve().parent

RECORDS = HERE / "data/records"

GRAVITY = 9.80665

PERIODS = np.unique(np.r_[np.geomspace(0.05, 4.0, 120), 0.3, 1.0, 2.0])

def load_record(name: str) -> tuple[np.ndarray, float]:
    """Read bundled acceleration in m/s² and its sampling interval in seconds."""
    path = RECORDS / f"{name}.csv"
    header = path.read_text(encoding="utf-8").splitlines()[0]
    interval = float(header.split("=", 1)[1])
    return np.loadtxt(path, skiprows=2), interval

def pseudo_acceleration(
    accel: np.ndarray,
    dt: float,
    periods: np.ndarray,
    damping: float = 0.05,
    correction_time: float | None = None,
    samples_per_cycle: int = 20,
) -> np.ndarray:
    """Compute peak pseudo-acceleration in g for initially resting oscillators.

    Args:
        accel: Stored acceleration in m/s², linearly interpolated between samples.
        dt: Source sampling interval in seconds.
        periods: Oscillator periods in seconds.
        damping: Fraction of critical damping.
        correction_time: Optional high-pass time constant, matching Modelica Record.
        samples_per_cycle: Minimum output samples per oscillator cycle.

    Returns:
        Peak pseudo-accelerations including five periods of post-record response.
    """
    source_time = np.arange(len(accel)) * dt
    out = []
    for period in periods:
        step = dt / max(1, int(np.ceil(dt * samples_per_cycle / period)))
        time = np.arange(0, source_time[-1] + 5 * period + step / 2, step)
        forcing = np.interp(time, source_time, accel, right=0.0)
        omega = 2 * np.pi / period
        if correction_time is None:
            matrix = [[0, 1], [-(omega**2), -2 * damping * omega]]
            inputs, outputs = [[0], [-1]], [[1, 0]]
        else:
            # Third state is the low-frequency estimate subtracted by Record.mo.
            matrix = [
                [0, 1, 0],
                [-(omega**2), -2 * damping * omega, 1],
                [0, 0, -1 / correction_time],
            ]
            inputs, outputs = [[0], [-1], [1 / correction_time]], [[1, 0, 0]]
        system = StateSpace(matrix, inputs, outputs, [[0]])
        displacement = lsim(system, forcing, time, interp=True)[1]
        out.append(omega**2 * np.max(np.abs(displacement)) / GRAVITY)
    return np.asarray(out)

def design_curve(periods: np.ndarray, plateau: float, corner: float) -> np.ndarray:
    """Return an illustrative rise, plateau and 1/T curve normalized by PGA."""
    rise = corner / 5
    return np.where(
        periods < rise,
        1 + (plateau - 1) * periods / rise,
        np.where(periods <= corner, plateau, plateau * corner / periods),
    )

def fit_design_spectrum(stack: np.ndarray) -> dict[str, float]:
    """Fit the illustrative shape to the component-wise 84th percentile.

    This log-residual fit is neither a bounding envelope nor a code spectrum.
    """
    target = np.percentile(stack, 84, axis=0)
    fit = least_squares(
        lambda p: np.log(design_curve(PERIODS, *p)) - np.log(target),
        [3.0, 0.6],
        bounds=([1.0, 0.1], [10.0, 2.0]),
    )
    return {"plateau": float(fit.x[0]), "corner": float(fit.x[1])}


BLUE, ORANGE, GREY, INK = "#1b6ca8", "#c8501e", "#8a9199", "#222222"

SHIFT_PERIODS = np.array([1.05, 3.0])

CASES = [
    ("Northridge1994", "Northridge 1994", BLUE),
    ("Kobe1995", "Kobe 1995", ORANGE),
]

RECORD_IDS = {"Northridge1994": 3, "Kobe1995": 4}

def save(fig, name: str) -> None:
    """Export a figure at readable resolution and release its canvas."""
    fig.savefig(HERE / "images" / name, dpi=170, bbox_inches="tight")
    plt.close(fig)

def zigzag(ax, x0, y0, x1, y1, teeth=6, amp=0.13, color=INK):
    """Draw an axial spring or resistor between two points."""
    along = np.array([x1 - x0, y1 - y0])
    normal = np.array([-along[1], along[0]]) / np.hypot(*along)
    points = [
        np.array([x0, y0])
        + a * along
        + (0 if i in (0, 2 * teeth) else amp * (-1) ** i) * normal
        for i, a in enumerate(np.linspace(0, 1, 2 * teeth + 1))
    ]
    ax.plot(*zip(*points), color=color, lw=1.6)

def rlc_analogy() -> None:
    """Show consistent horizontal mechanics and an explicitly measured RLC output."""
    fig, ax = plt.subplots(figsize=(10, 4.0))
    ax.set(xlim=(0, 11), ylim=(0, 4.5))
    ax.axis("off")
    ax.plot([0.5, 0.5, 4.2], [3.8, 1.1, 1.1], color=GREY, lw=3)
    ax.add_patch(plt.Rectangle((3, 1.6), 1, 2, fc="#d7e6f2", ec=INK))
    ax.text(3.5, 2.65, "$m$", ha="center", va="center", fontsize=16)
    zigzag(ax, 0.5, 3.25, 3, 3.25)
    ax.text(1.7, 3.6, "spring $k$", ha="center")
    ax.plot([0.5, 1.5], [1.95, 1.95], color=INK)
    ax.plot([2.1, 1.5, 1.5, 2.1], [1.7, 1.7, 2.2, 2.2], color=INK)
    ax.plot([1.85, 1.85], [1.74, 2.16], color=INK)
    ax.plot([1.85, 3], [1.95, 1.95], color=INK)
    ax.text(1.7, 2.5, "damper $c$", ha="center")
    ax.annotate(
        "", (4.0, 4.0), (3.0, 4.0), arrowprops={"arrowstyle": "->", "color": BLUE}
    )
    ax.text(3.5, 4.15, "$x$", ha="center", color=BLUE)
    ax.annotate(
        "", (3.7, 0.75), (1.0, 0.75), arrowprops={"arrowstyle": "<->", "color": BLUE}
    )
    ax.text(2.3, 0.35, "moving base, acceleration $a_g$", ha="center", color=BLUE)
    for y, label in [
        (3.5, "$m \\leftrightarrow L$"),
        (2.7, "$c \\leftrightarrow R$"),
        (1.9, "$k \\leftrightarrow 1/C$"),
    ]:
        ax.text(5.05, y, label, ha="center", fontsize=13)
    ax.plot([6.5, 6.5, 6.8], [1.25, 3.7, 3.7], color=INK)
    for i in range(4):
        angle = np.linspace(np.pi, 0, 30)
        ax.plot(
            6.95 + 0.3 * i + 0.15 * np.cos(angle), 3.7 + 0.25 * np.sin(angle), color=INK
        )
    zigzag(ax, 8.0, 3.7, 9.6, 3.7)
    ax.plot([9.6, 10, 10], [3.7, 3.7, 2.8], color=INK)
    ax.plot([9.7, 10.3], [2.8, 2.8], color=INK, lw=2)
    ax.plot([9.7, 10.3], [2.6, 2.6], color=INK, lw=2)
    ax.plot([10, 10, 6.5], [2.6, 1.25, 1.25], color=INK)
    ax.add_patch(plt.Circle((6.5, 2.45), 0.3, fc="white", ec=BLUE, zorder=3))
    ax.text(6.5, 2.45, "~", ha="center", va="center", color=BLUE, zorder=4)
    ax.text(6.9, 2.45, "$V_{in} \\leftrightarrow -m a_g$", color=BLUE, fontsize=10)
    ax.text(7.35, 4.15, "$L$", ha="center")
    ax.text(8.8, 4.15, "$R$", ha="center")
    ax.text(10.4, 2.7, "$C$", va="center")
    ax.annotate("", (9.2, 3.15), (8.4, 3.15), arrowprops={"arrowstyle": "->"})
    ax.text(8.8, 2.85, "current $i=\\dot{q}$", ha="center", fontsize=10)
    ax.text(8.4, 0.75, "Capacitor voltage $V_C=q/C$", ha="center", fontsize=10)
    ax.text(
        8.4, 0.35, "relative displacement $x$ ↔ charge $q$", ha="center", fontsize=10
    )
    save(fig, "rlc_analogy.png")

def comparison_data() -> dict:
    """Calculate spectra and bars with identical damping and baseline processing."""
    result = {}
    selected = np.array([0.3, 1.0, 2.0])
    for name, label, color in CASES:
        accel, dt = load_record(name)
        sa = pseudo_acceleration(accel, dt, PERIODS, 0.02, correction_time=5.0)
        peak_sa = np.array([sa[np.flatnonzero(PERIODS == p)[0]] for p in selected])
        result[name] = {
            "label": label,
            "color": color,
            "accel": accel,
            "dt": dt,
            "sa": sa,
            "pga": float(np.abs(accel).max() / GRAVITY),
            "peaks_mm": 1000 * peak_sa * GRAVITY * (selected / (2 * np.pi)) ** 2,
        }
    return result

def isolation_rlc() -> None:
    """Show mass inductance in series with parallel building and isolator branches."""
    fig, (mechanical, circuit) = plt.subplots(
        1, 2, figsize=(13.5, 4.6), gridspec_kw={"width_ratios": [1, 1.35]}
    )
    fig.subplots_adjust(left=0.02, right=0.98, bottom=0.02, top=0.98, wspace=0.1)
    for ax in (mechanical, circuit):
        ax.set(xlim=(0, 10), ylim=(0, 8))
        ax.axis("off")
    circuit.set(xlim=(0, 13))

    # Retain building inertia above a foundation with prescribed ground motion.
    for x in (3, 6):
        mechanical.plot([x, x], [3.0, 7.3], color=BLUE, lw=4)
    for y in (4.4, 5.85, 7.3):
        mechanical.plot([3, 6], [y, y], color=BLUE, lw=4)
    mechanical.text(4.5, 6.4, "$m, k_b, c_b$", ha="center", fontsize=12)
    mechanical.plot([2.7, 6.3], [3.0, 3.0], color=INK, lw=6)
    mechanical.add_patch(
        plt.Rectangle((1, 0.45), 7, 0.55, fc="#dde1e5", ec=GREY, lw=1.5)
    )
    mechanical.text(
        4.5, 0.05, "Foundation follows ground: $a_g$",
        ha="center", color=BLUE, fontsize=10,
    )
    for level in range(6):
        y = 1.15 + 0.27 * level
        left = 3.05 + 0.055 * level
        mechanical.add_patch(
            plt.Rectangle((left, y), 2.3, 0.23, fc="#fce4d6", ec=ORANGE, lw=0.8)
        )
        mechanical.plot([left, left + 2.3], [y, y], color=INK, lw=1.5)
    mechanical.add_patch(
        plt.Rectangle((4.02, 1.15), 0.38, 1.6, fc=ORANGE, ec=INK, lw=0.8)
    )
    for y in (1.0, 2.85):
        mechanical.plot([2.8, 6.0], [y, y], color=INK, lw=4)
    mechanical.annotate(
        "Rubber + steel\nlayers",
        (3.1, 1.8),
        (0.2, 2.0),
        arrowprops={"arrowstyle": "->", "color": INK},
        fontsize=10,
    )
    mechanical.annotate(
        "Lead core",
        (4.2, 2.2),
        (6.3, 2.0),
        arrowprops={"arrowstyle": "->", "color": ORANGE},
        fontsize=10,
        color=ORANGE,
    )
    mechanical.annotate(
        "", (6.5, 3.6), (2.5, 3.6), arrowprops={"arrowstyle": "<->"}
    )
    mechanical.text(
        4.5, 3.83, "Isolator displacement $x_{iso}$", ha="center", fontsize=10,
        bbox={"facecolor": "white", "edgecolor": "none", "pad": 1},
    )
    mechanical.text(
        0.3, 6.1, "Elastic\nsuperstructure", fontsize=10, color=BLUE
    )

    # Force-voltage dual: mechanical layers in series become parallel RC branches.
    circuit.plot([1, 1, 2], [1.7, 6.0, 6.0], color=BLUE)
    for i in range(4):
        angle = np.linspace(np.pi, 0, 30)
        circuit.plot(
            2.17 + 0.34 * i + 0.17 * np.cos(angle),
            6.0 + 0.3 * np.sin(angle), color=BLUE,
        )
    circuit.plot([3.36, 9, 9], [6.0, 6.0, 5.3], color=BLUE)
    circuit.plot([5, 5], [6.0, 5.3], color=ORANGE)
    for x, suffix, color in [(5, "iso", ORANGE), (9, "b", BLUE)]:
        zigzag(circuit, x, 5.3, x, 4.15, amp=0.16, color=color)
        circuit.plot([x, x], [4.15, 3.45], color=color)
        circuit.plot([x - .38, x + .38], [3.45, 3.45], color=color, lw=2)
        circuit.plot([x - .38, x + .38], [3.2, 3.2], color=color, lw=2)
        circuit.plot([x, x], [3.2, 1.7], color=color)
        circuit.text(x + .45, 4.7, f"$R_{{{suffix}}}$ ↔ $c_{{{suffix}}}$", color=color)
        circuit.text(x + .45, 3.15, f"$C_{{{suffix}}}$ ↔ $1/k_{{{suffix}}}$", color=color)
    circuit.plot([1, 9], [1.7, 1.7], color=BLUE)
    circuit.plot([5, 5], [1.7, 6.0], "o", color=INK, ms=4)
    circuit.add_patch(plt.Circle((1, 4.2), .4, fc="white", ec=INK, zorder=3))
    circuit.text(1, 4.2, "~", ha="center", va="center", zorder=4)
    circuit.text(2.6, 6.65, "$L$ ↔ $m$", color=BLUE, ha="center", fontsize=12)
    circuit.text(9.5, 7.45, "Building", color=BLUE, ha="center", weight="bold")
    circuit.text(
        5.0, 7.45, "Isolator", color=ORANGE, ha="center", weight="bold"
    )
    circuit.text(2.6, 2.65, "$V_{in}$ ↔ $-m a_g$", ha="center", fontsize=10)
    circuit.plot([9, 11.9], [6, 6], color=GREY, lw=.8, ls=":")
    circuit.plot([9, 11.9], [1.7, 1.7], color=GREY, lw=.8, ls=":")
    circuit.annotate(
        "", (11.9, 6), (11.9, 1.7), arrowprops={"arrowstyle": "<->"}
    )
    circuit.text(12.15, 3.85, "$V_{out}$", va="center", fontsize=12)
    circuit.text(
        6.5, .45, "Acceleration transmissibility ↔ $|V_{out}/V_{in}|$",
        ha="center", fontsize=11,
    )
    save(fig, "isolation_rlc.png")

def same_pga(data: dict) -> None:
    """Lead with observed ground peaks and the contrasting oscillator responses."""
    fig = plt.figure(figsize=(10, 4.7), layout="constrained")
    grid = fig.add_gridspec(2, 2, width_ratios=(1, 1.15))
    bars_ax = fig.add_subplot(grid[:, 1])
    for row, (name, item) in enumerate(data.items()):
        ax = fig.add_subplot(grid[row, 0])
        time = np.arange(len(item["accel"])) * item["dt"]
        ax.plot(time, item["accel"] / GRAVITY, color=item["color"], lw=0.6)
        ax.set(
            xlim=(0, 45),
            ylim=(-0.56, 0.56),
            ylabel="Ground accel. [g]",
        )
        ax.text(
            .98, .86, f"{item['label']} · PGA {item['pga']:.2f} g",
            transform=ax.transAxes, color=item["color"], fontsize=10, ha="right",
        )
        if row == 1:
            ax.set_xlabel("Time [s]")
        bars = bars_ax.bar(
            np.arange(3) + (row - 0.5) * 0.36,
            item["peaks_mm"],
            0.34,
            color=item["color"],
            label=item["label"],
        )
        bars_ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=10)
    ratio = data["Northridge1994"]["peaks_mm"][1] / data["Kobe1995"]["peaks_mm"][1]
    bars_ax.text(1, 390, f"{ratio:.2f}×", ha="center", weight="bold", color=BLUE)
    bars_ax.set(
        xticks=np.arange(3),
        xticklabels=["0.3 s", "1.0 s", "2.0 s"],
        xlabel="Natural period",
        ylabel="Peak relative displacement [mm]",
        ylim=(0, 480),
    )
    bars_ax.legend(frameon=False, loc="upper left", fontsize=9)
    save(fig, "same_pga.png")

BEARING_QD = 66666.6666667
BEARING_K1 = 7e6
BEARING_K2 = 7e5
# Ten 20 t floors plus 120 m of HEB500 (238.6 cm2, 7850 kg/m3) above the bearing.
ISOLATED_MASS = 10 * 20000 + 120 * 238.6e-4 * 7850


def bearing_at_peak(record: str) -> tuple[float, float]:
    """Return the Figure 6 bearing's secant period and loop damping at peak travel."""
    peaks = json.loads(
        (HERE / f"data/{record}_frame_summary.json").read_text(encoding="utf-8")
    )["peaks"]
    travel, force = peaks["isolationTravel"], peaks["isolationForce"]
    yield_travel = BEARING_QD / (BEARING_K1 - BEARING_K2)
    period = 2 * np.pi * np.sqrt(ISOLATED_MASS * travel / force)
    damping = 2 * BEARING_QD * (travel - yield_travel) / (np.pi * force * travel)
    return float(period), float(damping)


def spectrum_bank(data: dict) -> None:
    """Compare fixed-base and isolated spring-force demand, one record per panel."""
    saved = {
        "fixed_period_s": float(SHIFT_PERIODS[0]),
        "fixed_damping_ratio": 0.02,
        "correction_time_s": 5.0,
        "interpretation": (
            "Isolated point: Figure 6 bearing linearised at its simulated peak "
            "travel (secant period, hysteretic loop damping), frame rigid above"
        ),
        "records": {},
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), sharey=True,
                             layout="constrained")
    for ax, (name, item) in zip(axes, data.items()):
        iso_period, iso_damping = bearing_at_peak(name)
        marks = np.array([SHIFT_PERIODS[0], iso_period])
        periods = np.unique(np.r_[PERIODS, marks])
        fixed, isolated = (
            pseudo_acceleration(
                item["accel"], item["dt"], periods, damping, correction_time=5.0
            )
            for damping in (0.02, iso_damping)
        )
        points = [
            fixed[np.flatnonzero(periods == marks[0])[0]],
            isolated[np.flatnonzero(periods == marks[1])[0]],
        ]
        ax.plot(periods, fixed, color="#aeb5bc", lw=1.6, label="Fixed base")
        ax.plot(periods, isolated, color="#aeb5bc", lw=1.6, ls="--",
                label="Figure 6 bearing")
        ax.vlines(marks, 0, points, color=GREY, ls=":", lw=1, zorder=0)
        for point, (period, value, marker) in enumerate(
            zip(marks, points, ("s", "o"))
        ):
            ax.plot(period, value, marker, color=item["color"], ms=9, zorder=3)
            ax.annotate(
                f"{value:.2f} g", (period, value), xytext=(9, 10),
                textcoords="offset points", color=item["color"],
                fontsize=12, weight="bold",
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1},
            )
        ax.text(.97, .72, item["label"], transform=ax.transAxes, ha="right",
                color=item["color"], fontsize=11, weight="bold")
        ax.set(xlim=(0, 4), xticks=np.arange(0, 4.01, .5),
               xlabel="Natural period [s]")
        ax.grid(axis="y", color="#edf0f2", lw=.7)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, loc="upper right", fontsize=9)
        saved["records"][name] = {
            "isolated_period_s": iso_period,
            "isolated_damping_ratio": iso_damping,
            "pseudo_acceleration_g": [float(v) for v in points],
        }
    axes[0].set_ylabel("Pseudo-acceleration [g]")
    axes[0].set_ylim(0, 1.08 * max(line.get_ydata().max()
                                   for ax in axes for line in ax.get_lines()))
    save(fig, "spectrum_bank.png")
    (HERE / "data/isolation_period_shift.json").write_text(
        json.dumps(saved, indent=2) + "\n", encoding="utf-8"
    )

def design_spectrum() -> dict:
    """Show the documented ensemble's spread separately from its illustrative fit."""
    table = pd.read_csv(HERE / "data/fema_p695_normalized_spectra.csv")
    if not np.allclose(table.period_s, PERIODS) or table.shape[1] != 45:
        raise ValueError(
            "Rebuild the 44-component ensemble for the current period grid"
        )
    stack = table.iloc[:, 1:].to_numpy().T
    low, median, high = np.percentile(stack, [16, 50, 84], axis=0)
    fit = fit_design_spectrum(stack)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), sharey=True, layout="constrained")
    axes[0].plot(PERIODS, stack.T, color=GREY, lw=0.55, alpha=0.4)
    for ax in axes:
        ax.fill_between(
            PERIODS, low, high, color=BLUE, alpha=0.16, label="16th–84th percentile"
        )
        ax.plot(PERIODS, median, color=BLUE, lw=2, label="Median")
        ax.set(xlabel="Natural period [s]", xlim=(0, 4), ylim=(0, None))
    axes[0].set_ylabel("Pseudo-acceleration / source PGA [-]")
    axes[0].legend(
        frameon=False, fontsize=9, loc="upper right", bbox_to_anchor=(1, .81)
    )
    axes[1].plot(PERIODS, high, color=BLUE, lw=1, ls="--", label="84th percentile")
    axes[1].plot(
        PERIODS,
        design_curve(PERIODS, **fit),
        color=ORANGE,
        lw=2.5,
        label="Illustrative fit to 84th percentile",
    )
    axes[1].annotate(
        "plateau",
        (0.35, fit["plateau"]),
        (0.45, fit["plateau"] + 1.5),
        arrowprops={"arrowstyle": "->", "color": ORANGE},
        color=ORANGE,
    )
    axes[1].annotate(
        "1/T branch",
        (2, fit["plateau"] * fit["corner"] / 2),
        (2.15, fit["plateau"] * fit["corner"] / 2 + 1.4),
        arrowprops={"arrowstyle": "->", "color": ORANGE},
        color=ORANGE,
    )
    axes[1].legend(
        frameon=False, fontsize=8, loc="upper right", bbox_to_anchor=(1, .81)
    )
    for ax, values in zip(
        axes,
        (np.interp(SHIFT_PERIODS, PERIODS, median), design_curve(SHIFT_PERIODS, **fit)),
    ):
        for period, label, marker, value in zip(
            SHIFT_PERIODS,
            (
                f"Without isolation\n{SHIFT_PERIODS[0]:.2f} s",
                f"With isolation\n{SHIFT_PERIODS[1]:.2f} s",
            ),
            ("s", "o"),
            values,
        ):
            ax.axvline(period, color=GREY, ls=":", lw=1, zorder=0)
            ax.plot(period, value, marker, color=INK, ms=8, zorder=5)
            ax.text(
                period, .98, label, transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=10, backgroundcolor="white",
            )
        ax.annotate(
            "", (SHIFT_PERIODS[1], values[1]), (SHIFT_PERIODS[0], values[0]),
            arrowprops={
                "arrowstyle": "-|>", "color": INK, "lw": 1.8,
                "connectionstyle": "arc3,rad=.18", "shrinkA": 7, "shrinkB": 7,
            },
        )
    save(fig, "design_fit.png")
    return fit

def transmissibility() -> None:
    """Show the series RLC circuit as a low-pass filter on two sine inputs."""
    damping = 0.02
    period = SHIFT_PERIODS[0]
    cutoff = np.sqrt(2) / period

    def gain(frequency):
        r = frequency * period
        return (1 + 2j * damping * r) / (1 - r**2 + 2j * damping * r)

    fig, axes = plt.subplot_mosaic(
        [["filter", "filter"], ["slow", "fast"]], figsize=(11, 7.6),
        layout="constrained", height_ratios=[1.2, 1],
    )
    curve = np.geomspace(0.1, 10, 800)
    top = axes["filter"]
    top.loglog(curve, np.abs(gain(curve)), color=INK, lw=2)
    top.axhline(1, color=GREY, lw=1, ls=":")
    top.axvspan(cutoff, 10, color="#e8f0f6", zorder=0)
    top.plot(cutoff, 1, "o", color=INK, ms=7, zorder=3)
    top.annotate(
        f"cutoff {cutoff:.2f} Hz", (cutoff, 1), xytext=(8, 10),
        textcoords="offset points", fontsize=10,
    )
    top.text(0.11, 1.4, "Passes", fontsize=11)
    top.text(3, 1.4, "Blocks", fontsize=11, color=BLUE)
    examples = [("slow", 0.3, 10), ("fast", 4.0, 2)]
    for key, frequency, duration in examples:
        value = gain(frequency)
        top.plot(frequency, abs(value), "s", color=ORANGE, ms=8, zorder=3)
        top.annotate(
            f"{frequency:g} Hz", (frequency, abs(value)), xytext=(0, 10),
            textcoords="offset points", ha="center", color=ORANGE, fontsize=10,
        )
        ax = axes[key]
        time = np.linspace(0, duration, 1000)
        phase = 2 * np.pi * frequency * time
        ax.plot(time, np.sin(phase), color="#aeb5bc", lw=1.6, label="In: $V_{in}$")
        ax.plot(time, abs(value) * np.sin(phase + np.angle(value)), color=INK,
                lw=2, label=f"Out: $V_{{out}}$ = {abs(value):.2f} × in")
        ax.set(xlabel="Time [s]", ylim=(-1.5, 1.9), xlim=(0, duration))
        ax.text(
            .02, .9, f"{frequency:g} Hz: {'passes' if key == 'slow' else 'blocked'}",
            transform=ax.transAxes, color=ORANGE, fontsize=11,
        )
        ax.axhline(0, color=GREY, lw=.6)
        ax.legend(frameon=False, loc="upper right", fontsize=9, ncol=2)
    axes["slow"].set_ylabel("Signal / input amplitude [-]")
    top.set(
        xlabel="Frequency [Hz]",
        ylabel="$|V_{out}/V_{in}|$ = mass / ground acceleration",
        xlim=(0.1, 10), ylim=(0.008, 30),
    )
    top.xaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%g"))
    save(fig, "transmissibility.png")

def frame_panels(
    name: str, keys: tuple[str, ...] = ("fixed", "isolated")
) -> list[Image.Image]:
    """Render geometry at export resolution, with labels in the outer layout."""
    frames = []
    with np.load(HERE / f"data/{name}_frame_animation.npz") as data:
        colors = ["#b0bec9", "#cac091", "#e4c358", "#eaa83a", "#dc6f36", "#cd3732"]
        bounds = [0.1, 0.3, 0.5, 0.7, 1.0]
        for index in range(len(data["time"])):
            fig = plt.figure(figsize=(4.2 * len(keys), 3.2), dpi=100)
            for column, key in enumerate(keys):
                ax = fig.add_axes([column / len(keys), 0, 1 / len(keys), 1])
                nodes = data[f"{key}_nodes"][index]
                columns = data[f"{key}_columns"][..., index]
                beams = data[f"{key}_beams"][..., index]
                x0 = data[f"{key}_nodes"][0, 0, 0, 0]
                height = data[f"{key}_nodes"][0, -1, 0, 1]
                ax.set(
                    xlim=(x0 - 3.5, x0 + 9.5), ylim=(-0.9, height + 1.5),
                    aspect="equal",
                )
                ax.axis("off")
                ax.fill_between([x0 - 3.5, x0 + 9.5], -0.9, 0, color="#9ba390")
                if key == "isolated":
                    ax.fill_between(nodes[0, :, 0], 0, nodes[0, :, 1], color="#8b5a2b")
                for level in range(len(nodes) - 1):
                    for side in range(2):
                        points = nodes[level : level + 2, side]
                        color = colors[
                            np.searchsorted(bounds, columns[level, side], side="right")
                        ]
                        ax.plot(
                            points[:, 0],
                            points[:, 1],
                            color=color,
                            lw=3.5,
                            solid_capstyle="butt",
                        )
                    color = colors[np.searchsorted(bounds, beams[level], side="right")]
                    ax.plot(
                        nodes[level + 1, :, 0],
                        nodes[level + 1, :, 1],
                        color=color,
                        lw=4,
                        solid_capstyle="butt",
                    )
            fig.canvas.draw()
            frames.append(
                Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")
            )
            plt.close(fig)
    return frames

def animation_legend(canvas: Image.Image, y: int) -> None:
    """Draw a shared stress key outside the animated geometry."""
    font_path = matplotlib.font_manager.findfont("DejaVu Sans")
    font = ImageFont.truetype(font_path, 22)
    draw = ImageDraw.Draw(canvas)
    draw.text((30, y), "Member stress / yield stress", font=font, fill=INK)
    colors = ["#b0bec9", "#cac091", "#e4c358", "#eaa83a", "#dc6f36", "#cd3732"]
    labels = ["<0.1", "0.1–0.3", "0.3–0.5", "0.5–0.7", "0.7–1.0", "≥1.0"]
    for col, (color, label) in enumerate(zip(colors, labels)):
        x = 30 + col * 150
        draw.rectangle((x, y + 40, x + 22, y + 62), fill=color)
        draw.text((x + 30, y + 37), label, font=font, fill=INK)


def isolation_animation() -> None:
    """Compare fixed and isolated frames for both selected records."""
    font_path = matplotlib.font_manager.findfont("DejaVu Sans")
    font = ImageFont.truetype(font_path, 28)
    small = ImageFont.truetype(font_path, 23)
    frames = []
    panels = [frame_panels(name) for name, _, _ in CASES]
    pgas = [np.abs(load_record(name)[0]).max() / GRAVITY for name, _, _ in CASES]
    samples = []
    for name, _, _ in CASES:
        with np.load(HERE / f"data/{name}_frame_animation.npz") as data:
            samples.append({key: data[key] for key in data.files})
    if len(panels[0]) != len(panels[1]):
        raise ValueError("Both animation rows must have the same frame count")
    for index in range(len(panels[0])):
        canvas = Image.new("RGB", (960, 1000), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((270, 18), "Fixed base", anchor="mt", font=font, fill=INK)
        draw.text((690, 18), "Base isolated", anchor="mt", font=font, fill=INK)
        for row, (_, event, color) in enumerate(CASES):
            y = 70 + row * 420
            data = samples[row]
            draw.line((30, y - 12, 930, y - 12), fill="#d9dfe5", width=2)
            draw.text((30, y), event, font=font, fill=color)
            draw.text((400, y + 3), f"PGA {pgas[row]:.2f} g", font=small, fill=INK)
            draw.text(
                (930, y + 3), f"t = {data['time'][index]:.2f} s", anchor="rt",
                font=small, fill=INK,
            )
            canvas.paste(panels[row][index], (60, y + 40))
            for col, key in enumerate(("fixed", "isolated")):
                peak = max(
                    data[f"{key}_columns"][..., index].max(),
                    data[f"{key}_beams"][..., index].max(),
                )
                draw.text(
                    (270 + col * 420, y + 372),
                    f"Current max stress ratio: {peak:.2f}",
                    anchor="mt", font=small, fill=INK,
                )
        animation_legend(canvas, 918)
        frames.append(canvas)
    frames[0].save(
        HERE / "images/isolation_frames.gif",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        disposal=2,
    )


def fixed_base_animation() -> None:
    """Render fixed frames directly with synchronized record cursors."""
    font_path = matplotlib.font_manager.findfont("DejaVu Sans")
    font = ImageFont.truetype(font_path, 28)
    small = ImageFont.truetype(font_path, 23)
    panels = [frame_panels(name, ("fixed",)) for name, _, _ in CASES]
    samples = []
    for name, _, _ in CASES:
        with np.load(HERE / f"data/{name}_frame_animation.npz") as data:
            samples.append({key: data[key] for key in data.files})
    fig = plt.figure(figsize=(9.6, 2.7), dpi=100)
    cursors = []
    for col, (name, _, color) in enumerate(CASES):
        accel, dt = load_record(name)
        ax = fig.add_axes([(105 + col * 480) / 960, 0.26, 320 / 960, 0.67])
        ax.plot(np.arange(len(accel)) * dt, accel / GRAVITY, color=color, lw=0.7)
        ax.axhline(0, color=GREY, lw=0.5, zorder=0)
        ax.axvspan(*samples[col]["time"][[0, -1]], color=color, alpha=0.08)
        cursors.append(ax.axvline(samples[col]["time"][0], color=INK, lw=1.5))
        ax.set(xlim=(0, 45), ylim=(-0.56, 0.56), yticks=[-0.5, 0, 0.5])
        ax.set_xlabel("Record time [s]", fontsize=16)
        ax.set_ylabel("Acceleration [g]", fontsize=16)
        ax.tick_params(labelsize=14)
        ax.spines[["top", "right"]].set_visible(False)
    frames = []
    pgas = [np.abs(load_record(name)[0]).max() / GRAVITY for name, _, _ in CASES]
    for index in range(len(panels[0])):
        canvas = Image.new("RGB", (960, 870), "white")
        draw = ImageDraw.Draw(canvas)
        for col, (_, event, color) in enumerate(CASES):
            x = 240 + col * 480
            data = samples[col]
            draw.text((x, 18), event, anchor="mt", font=font, fill=color)
            draw.text(
                (x, 61), f"PGA {pgas[col]:.2f} g  ·  t = {data['time'][index]:.2f} s",
                anchor="mt", font=small, fill=INK,
            )
            canvas.paste(panels[col][index], (30 + col * 480, 103))
            peak = max(
                data["fixed_columns"][..., index].max(),
                data["fixed_beams"][..., index].max(),
            )
            draw.text(
                (x, 436), f"Current max stress ratio: {peak:.2f}",
                anchor="mt", font=small, fill=INK,
            )
            cursors[col].set_xdata([data["time"][index]] * 2)
        fig.canvas.draw()
        records = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")
        canvas.paste(records, (0, 480))
        animation_legend(canvas, 760)
        frames.append(canvas)
    plt.close(fig)
    frames[0].save(
        HERE / "images/fixed_base_frames.gif",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        disposal=2,
    )


SOURCE = "https://sp3risk.com/ground-motion-sets/"

ASSETS = (
    "https://s3.us-west-2.amazonaws.com/static-assets.hbrisk.com/ground-motion-sets/"
)

ARCHIVE = "2b_ATC-63_Far-Field_GroundMotionAccelTextFiles_Unscaled_Original.zip"

SUMMARY = "1_ReadMe_ATC-63_GroundMotionSet_FarField_SummaryFile.xls"

def build(archive_path: Path, summary_path: Path) -> None:
    """Select the published 22 pairs and save spectra with per-component provenance."""
    import xlrd

    workbook = xlrd.open_workbook(summary_path)
    events = workbook.sheet_by_name("Table A-4A")
    sites = workbook.sheet_by_name("Table A-4B")
    files = workbook.sheet_by_name("Table A-4C")
    event_by_id = {
        int(events.cell_value(i, 0)): events.row_values(i) for i in range(2, 24)
    }
    site_by_id = {
        int(sites.cell_value(i, 0)): sites.row_values(i) for i in range(2, 24)
    }
    spectra, metadata = {}, []
    with zipfile.ZipFile(archive_path) as archive:
        members = {"/".join(n.split("/")[1:]): n for n in archive.namelist()}
        for row in range(3, 25):
            pair, rsn, low_frequency, *rest = files.row_values(row)
            event, site = event_by_id[int(pair)], site_by_id[int(pair)]
            for component, stem in enumerate(rest[:2], start=1):
                filename = f"{stem}.AT2"
                raw = archive.read(members[filename])
                lines = raw.decode("ascii").splitlines()
                numbers = re.findall(r"[\d.]+(?:[Ee][+-]?\d+)?", lines[3])
                count, dt = int(numbers[0]), float(numbers[1])
                acceleration = np.fromstring(" ".join(lines[4:]), sep=" ")
                if len(acceleration) != count or "UNITS OF G" not in lines[2].upper():
                    raise ValueError(f"Unexpected sample count or units: {filename}")
                pga = float(np.max(np.abs(acceleration)))
                key = f"{int(pair)}{component}"
                spectra[key] = (
                    pseudo_acceleration(acceleration * GRAVITY, dt, PERIODS) / pga
                )
                metadata.append(
                    {
                        "component_id": key,
                        "pair_id": int(pair),
                        "peer_rsn": int(rsn),
                        "event": event[3],
                        "year": int(event[2]),
                        "magnitude": event[1],
                        "station": event[4],
                        "component_file": filename,
                        "source_header": lines[1].strip(),
                        "site_class": site[1],
                        "vs30_m_s": site[2],
                        "lowest_usable_frequency_hz": low_frequency,
                        "source_pga_g": pga,
                        "scale_to_1g": 1 / pga,
                        "sample_interval_s": dt,
                        "n_samples": count,
                        "duration_s": (count - 1) * dt,
                        "processing": "PEER processed; no additional high-pass filter",
                        "source_url": SOURCE,
                        "archive_url": ASSETS + ARCHIVE,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
                print(f"{len(metadata):02}/44 {filename}", flush=True)
    if len(spectra) != 44 or len({r["pair_id"] for r in metadata}) != 22:
        raise ValueError("The selected set must contain 22 pairs / 44 components")
    data = HERE / "data"
    data.mkdir(exist_ok=True)
    pd.DataFrame(metadata).to_csv(data / "fema_p695_records.csv", index=False)
    pd.DataFrame({"period_s": PERIODS, **spectra}).to_csv(
        data / "fema_p695_normalized_spectra.csv", index=False
    )
    provenance = {
        "archive_url": ASSETS + ARCHIVE,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "summary_url": ASSETS + SUMMARY,
        "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "selection": "Table A-4C rows for 22 pairs, joined to Tables A-4A and A-4B",
        "damping": 0.05,
        "additional_high_pass": False,
        "normalization": "Each component divided by its own source PGA",
        "weighting": "Equal component weights; paired components are correlated",
        "solver": "scipy.signal.lsim, linear interpolation, initially at rest",
        "output_sampling": "At least 20 samples per oscillator cycle",
        "post_record_tail": "Zero input for five oscillator periods",
    }
    (data / "fema_p695_provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )


MODEL = "TenStoreyFrame"

METRICS = [
    "fixedRoofDisplacement",
    "isolatedRoofDisplacement",
    "isolationTravel",
    "isolationForce",
    "fixedStressRatio",
    "isolatedStressRatio",
]

def verify() -> None:
    """Check the changed calculations against independent integration and the FMU."""
    from fmpy import simulate_fmu

    fmu_path = HERE / "fmu/SdofSpectrum.fmu"
    with zipfile.ZipFile(fmu_path) as archive:
        description = ET.fromstring(archive.read("modelDescription.xml"))
    assert description.find("ModelExchange") is not None, "Use a Model Exchange FMU"

    # A non-earthquake forcing checks the response equation independently of records.
    dt, period, damping = 0.001, 0.7, 0.05
    time = np.arange(0, 6 + dt / 2, dt)
    forcing = np.sin(2 * np.pi * 1.3 * time) * np.sin(np.pi * time / 6) ** 2
    omega = 2 * np.pi / period

    def rhs(t, state):
        x, velocity = state
        accel = np.interp(t, time, forcing, right=0.0)
        return [velocity, -(omega**2) * x - 2 * damping * omega * velocity - accel]

    independent = solve_ivp(rhs, (0, 9.5), [0, 0], rtol=1e-9, atol=1e-11, max_step=dt)
    reference = omega**2 * np.max(np.abs(independent.y[0])) / GRAVITY
    computed = pseudo_acceleration(forcing, dt, np.array([period]), damping)[0]
    assert abs(computed / reference - 1) < 0.001, "Independent solver mismatch"

    comparison = json.loads(
        (HERE / "data/figure_values.json").read_text(encoding="utf-8")
    )
    short_periods = np.array([0.05, 0.1, 0.3, 1.0, 2.0, 4.0])
    worst_sampling, worst_fmu, worst_fmu_refinement = 0.0, 0.0, 0.0
    for name, _, _ in CASES:
        record_id = RECORD_IDS[name]
        accel, interval = load_record(name)
        coarse = pseudo_acceleration(accel, interval, short_periods, 0.02, 5.0)
        fine = pseudo_acceleration(accel, interval, short_periods, 0.02, 5.0, 40)
        worst_sampling = max(worst_sampling, float(np.max(np.abs(coarse / fine - 1))))
        outputs = [f"relativeDisplacement[{i}]" for i in (2, 3, 4)]
        peaks = []
        for tolerance, output_interval in [(1e-7, 1e-3), (1e-8, 5e-4)]:
            result = simulate_fmu(
                fmu_path,
                fmi_type="ModelExchange",
                solver="CVode",
                start_values={"recordName": record_id},
                stop_time=(len(accel) - 1) * interval + 20,
                relative_tolerance=tolerance,
                output_interval=output_interval,
                output=outputs,
            )
            peaks.append(np.array([
                1000 * np.max(np.abs(result[key])) for key in outputs
            ]))
        fmu_peaks, refined_fmu_peaks = peaks
        worst_fmu_refinement = max(
            worst_fmu_refinement,
            float(np.max(np.abs(fmu_peaks / refined_fmu_peaks - 1))),
        )
        saved = np.array(comparison[name]["peaks_mm"])
        worst_fmu = max(worst_fmu, float(np.max(np.abs(fmu_peaks / saved - 1))))
    assert (
        worst_sampling < 0.015
    ), f"Sampling refinement changes peaks by {worst_sampling:.2%}"
    assert worst_fmu < 0.005, f"FMU and SciPy differ by {worst_fmu:.2%}"
    assert worst_fmu_refinement < 0.001, (
        f"CVODE tolerance and sampling refinement changes peaks by "
        f"{worst_fmu_refinement:.2%}"
    )

    records = pd.read_csv(HERE / "data/fema_p695_records.csv")
    spectra = pd.read_csv(HERE / "data/fema_p695_normalized_spectra.csv")
    assert len(records) == 44 and records.pair_id.nunique() == 22, "Wrong ensemble size"
    assert records.groupby("pair_id").size().eq(2).all(), "Incomplete horizontal pair"
    assert len(records[["event", "year"]].drop_duplicates()) == 14, "Wrong event count"
    assert set(spectra.columns[1:]) == set(
        records.component_id.astype(str)
    ), "Record mismatch"
    assert np.allclose(spectra.period_s, PERIODS), "Period grid mismatch"
    assert np.isfinite(spectra.to_numpy()).all(), "Non-finite spectral values"
    assert (spectra.iloc[:, 1:] > 0).all().all(), "Non-positive spectral values"

    blog = (HERE / "isolation-spectrum.md").read_text(encoding="utf-8")
    plain = re.sub(r"<!--.*?-->", "", blog, flags=re.S)
    plain = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    words = len(plain.split())
    assert words < 1500, f"Article has {words} words"
    for target in re.findall(r"!?\[[^\]]*\]\(([^)]*)\)", blog):
        if not target.startswith("https://"):
            assert (HERE / target).is_file(), f"Missing article asset: {target}"
    assert re.findall(r"\*Figure (\d):", blog) == list("12345678"), "Figure numbering"
    notebook = json.loads(
        (HERE / "isolation_spectrum.ipynb").read_text(encoding="utf-8")
    )
    methods = [
        cell for cell in notebook["cells"]
        if "methods" in cell["metadata"].get("tags", [])
    ]
    assert len(methods) == 1, "Keep one methods appendix in the notebook"
    assert "".join(methods[0]["source"]).startswith("## Methods and provenance")
    frame_peaks = []
    frame_periods = {}
    for record, label, _ in CASES:
        assert label in blog, f"Missing article record: {label}"
        frame_summary = json.loads(
            (HERE / f"data/{record}_frame_summary.json").read_text(encoding="utf-8")
        )
        frame = pd.read_csv(HERE / f"fmu/frame_{record}_reference.csv")
        accel, interval = load_record(record)
        assert frame_summary["record"] == record, "Wrong frame input record"
        assert frame_summary["input_acceleration_correlation"] > .95, (
            "Frame excitation does not match the named record"
        )
        assert frame.time.iloc[-1] >= (len(accel) - 1) * interval, (
            "Incomplete frame simulation"
        )
        tail_time = np.arange((len(accel) - 1) * interval + 1, frame.time.iloc[-1], .01)
        tail_roof = np.interp(tail_time, frame.time, frame.fixedRoofDisplacement)
        maxima = find_peaks(tail_roof, distance=50)[0]
        measured_period = float(np.median(np.diff(tail_time[maxima])))
        assert abs(measured_period - SHIFT_PERIODS[0]) < .03, (
            f"{record}: frame period is {measured_period:.3f} s, expected about 1.05 s"
        )
        frame_periods[record] = measured_period
        for name in METRICS:
            peak = frame_summary["peaks"][name]
            assert np.isclose(frame[name].abs().max(), peak), (
                f"Frame peak mismatch: {name}"
            )
        frame_peaks.append(frame_summary["peaks"]["fixedRoofDisplacement"])
        assert frame_summary["storeys"] == 10, "Opening frame must have ten storeys"
        event = label.rsplit(" ", 1)[0]
        assert f"{1000 * frame_peaks[-1]:.0f} mm under {event}" in blog, (
            f"Opening displacement does not match the {event} frame"
        )
        assert f"{comparison[record]['source_pga_g']:.2f} g" in blog, (
            f"Opening PGA does not match {event}"
        )
        with np.load(HERE / f"data/{record}_frame_animation.npz") as samples:
            for key in ("fixed", "isolated"):
                assert samples[f"{key}_nodes"].shape == (120, 11, 2, 2), (
                    "Frame geometry"
                )
                height = np.diff(samples[f"{key}_nodes"][0, :, 0, 1])
                assert np.max(np.abs(height - 3)) < .01, "Ten 3 m storeys"
            assert all(np.isfinite(samples[key]).all() for key in samples.files)
    assert frame_peaks[0] / frame_peaks[1] > 3, "Opening frame contrast is too small"
    assert comparison["Northridge1994"]["source_pga_g"] < (
        comparison["Kobe1995"]["source_pga_g"]
    ), "The larger frame response must come from the lower-PGA record"
    assert comparison["Northridge1994"]["peaks_mm"][1] / (
        comparison["Kobe1995"]["peaks_mm"][1]
    ) > 3.8, "Figure 2 must support the opening contrast near one second"
    report = {
        "article_words_including_alt_text": words,
        "sampling_refinement_max_relative_difference": worst_sampling,
        "fmu_max_relative_difference": worst_fmu,
        "fmu_solver": "FMPy CVODE, implicit BDF, Model Exchange",
        "fmu_relative_tolerance": 1e-7,
        "fmu_output_interval_s": 1e-3,
        "fmu_refined_relative_tolerance": 1e-8,
        "fmu_refined_output_interval_s": 5e-4,
        "fmu_refinement_max_relative_difference": worst_fmu_refinement,
        "independent_solver_relative_difference": abs(computed / reference - 1),
        "ensemble_components": 44,
        "station_pairs": 22,
        "earthquakes": 14,
        "frame_comparison_events": [name for name, _, _ in CASES],
        "frame_free_response_period_s": frame_periods,
    }
    (HERE / "data/verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


def generate_figures() -> None:
    """Reproduce all eight figures and save their numerical values."""
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
        }
    )
    data = comparison_data()
    same_pga(data)
    rlc_analogy()
    isolation_rlc()
    spectrum_bank(data)
    fit = design_spectrum()
    transmissibility()
    isolation_animation()
    fixed_base_animation()
    summary = {
        name: {
            "source_pga_g": item["pga"],
            "peaks_mm": item["peaks_mm"].tolist(),
        }
        for name, item in data.items()
    }
    summary["ensemble_fit"] = fit
    (HERE / "data/figure_values.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


def main() -> None:
    """Run a selected reproduction task from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("figures", help="Reproduce the eight article figures")
    commands.add_parser("verify", help="Check numerical results and article assets")
    ensemble = commands.add_parser("ensemble", help="Recompute FEMA ensemble data")
    ensemble.add_argument("archive", type=Path)
    ensemble.add_argument("summary", type=Path)
    args = parser.parse_args()
    matplotlib.use("Agg")
    if args.command == "figures":
        generate_figures()
    elif args.command == "verify":
        verify()
    elif args.command == "ensemble":
        build(args.archive, args.summary)


if __name__ == "__main__":
    main()
