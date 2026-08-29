"""Mooring line utilities — single-file distribution for blog_notebook.ipynb.

Required: numpy, pandas, scipy, onnxruntime
Optional: kaleido + Pillow (GIF export), dolfinx + mpi4py (FEM/Guyan, Docker)
"""
import json
import os
import time
import warnings
from dataclasses import dataclass

import numpy as np
import onnxruntime as rt
import pandas as pd
from scipy.optimize import brentq, fsolve

# ── OC4 DeepCwind geometry ────────────────────────────────────────────────

@dataclass(frozen=True)
class _OC4Mooring:
    n_lines: int = 3
    fairlead_radius: float = 40.868
    fairlead_depth: float = -14.0
    anchor_radius: float = 837.6
    anchor_depth: float = -200.0
    unstretched_length: float = 835.5
    diameter: float = 0.0766
    mass_per_length: float = 108.63      # kg/m in water (submerged, apparent mass — Robertson et al. 2014 Table 5-1; NOT the 113.35 kg/m dry mass density)
    axial_stiffness: float = 753_600_000.0  # N — Robertson et al. 2014 Table 5-1 "Equivalent Mooring Line Extensional Stiffness"
    bending_stiffness: float = 0.0
    nominal_pretension: float = 1_068_338.0  # OC4 still-water pretension (~1.07 MN) at 796.7 m equilibrium
    water_density: float = 1025.0
    gravity: float = 9.81

OC4Mooring = _OC4Mooring()


# ── Analytical catenary ───────────────────────────────────────────────────

def solve_catenary(horizontal_span: float, vertical_span: float,
                   line_length: float, w: float) -> dict:
    """Solve static catenary with seabed contact."""
    if line_length <= 0 or w <= 0:
        raise ValueError("line_length and w must be positive")

    is_near_vertical = horizontal_span < 1.0 and vertical_span > 10.0

    if is_near_vertical:
        def residual_1d(H):
            if H <= 0:
                return 1e10
            return (H / w) * np.arcsinh(w * line_length / H) - horizontal_span
        try:
            H = brentq(residual_1d, 0.001, 1e9, xtol=0.1)
        except (ValueError, RuntimeError):
            H = w * horizontal_span if horizontal_span > 0 else 0.1
        L_b, L_s = 0.0, line_length
    else:
        def residuals(params):
            H, L_b = params
            if H <= 0 or L_b < 0 or L_b >= line_length:
                return [1e10, 1e10]
            L_s = line_length - L_b
            z_end = np.sqrt((H / w) ** 2 + L_s ** 2) - H / w
            x_end = L_b + (H / w) * np.arcsinh(w * L_s / H)
            return [z_end - vertical_span, x_end - horizontal_span]

        H0 = w * (line_length**2 - vertical_span**2) / (2.0 * vertical_span) if vertical_span > 0 else w * horizontal_span
        H0 = max(H0, w * horizontal_span, w)
        L_b0 = max(line_length - np.sqrt(horizontal_span**2 + vertical_span**2), 0.0)
        result, _, ier, msg = fsolve(residuals, [H0, L_b0], full_output=True)
        if ier not in (1, 2, 3, 4) and float(np.linalg.norm(residuals(result))) > 2.0:
            raise RuntimeError(f"Catenary solver did not converge: {msg}")
        H, L_b = result
        L_b = max(L_b, 0.0)
        L_s = line_length - L_b

    return {
        "horizontal_tension": float(H),
        "fairlead_tension": float(np.sqrt(H**2 + (w * L_s)**2)),
        "anchor_tension": float(H),
        "seabed_length": float(L_b),
    }


# ── OC4 catenary reference data ───────────────────────────────────────────

OC4_REFERENCE = {
    "mean_tension_N": 1_068_338.0,
    "max_tension_N": 1_068_338.0,
    "min_tension_N": 530_178.0,
    "std_tension_N": 180_000.0,
    # 795.0 m: the sweep endpoint where the 1,068,338 N tension is evaluated
    # (still-water equilibrium is 796.7 m, where the catenary reads ~1.15 MN)
    "fairlead_horizontal_offset_m": 795.0,
}

_OC4_CASES_RAW = np.array([
    [773.0, 1.0, 200.0,   530_178],
    [775.0, 1.0, 200.0,   556_311],
    [777.0, 1.0, 200.0,   585_183],
    [779.0, 1.0, 200.0,   617_186],
    [781.0, 1.0, 200.0,   652_789],
    [783.0, 1.0, 200.0,   692_550],
    [785.0, 1.0, 200.0,   737_139],
    [787.0, 1.0, 200.0,   787_369],
    [789.0, 1.0, 200.0,   844_230],
    [791.0, 1.0, 200.0,   908_941],
    [793.0, 1.0, 200.0,   983_013],
    [795.0, 1.0, 200.0, 1_068_338],
])


def _derive_force_components(offset_m: float, tension_N: float) -> tuple[float, float]:
    cfg = OC4Mooring
    w = cfg.mass_per_length * cfg.gravity
    try:
        res = solve_catenary(offset_m, abs(cfg.fairlead_depth - cfg.anchor_depth),
                             cfg.unstretched_length, w)
        H, T_cat = res["horizontal_tension"], res["fairlead_tension"]
        if T_cat < 1.0:
            raise ValueError("near-zero tension")
        V = float(np.sqrt(max(T_cat**2 - H**2, 0.0)))
        scale = tension_N / float(np.sqrt(H**2 + V**2))
        return float(H * scale), float(V * scale)
    except (ValueError, RuntimeError, ArithmeticError) as exc:
        warnings.warn(f"solve_catenary failed at offset={offset_m}m ({exc}); using fallback.")
        theta = np.arctan2(0.8, 0.6)
        return float(tension_N * np.cos(theta)), float(tension_N * np.sin(theta))


def get_oc4_reference_point() -> dict:
    return OC4_REFERENCE.copy()


def get_oc4_dataframe() -> pd.DataFrame:
    rows = []
    for offset, pf, depth, tension in _OC4_CASES_RAW:
        fx, fz = _derive_force_components(float(offset), float(tension))
        rows.append({
            "fairlead_offset_m": float(offset),
            "pretension_factor": float(pf),
            "water_depth_m": float(depth),
            "fairlead_tension_N": float(tension),
            "horizontal_force_N": fx,
            "vertical_force_N": fz,
        })
    return pd.DataFrame(rows)


# ── Guyan reduction ───────────────────────────────────────────────────────

def guyan_reduce(K: np.ndarray, master_dofs: list[int]) -> tuple[np.ndarray, np.ndarray]:
    n = K.shape[0]
    slave_dofs = [i for i in range(n) if i not in set(master_dofs)]
    m_idx, s_idx = np.array(master_dofs), np.array(slave_dofs)
    K_mm = K[np.ix_(m_idx, m_idx)]
    K_ms = K[np.ix_(m_idx, s_idx)]
    K_sm = K[np.ix_(s_idx, m_idx)]
    K_ss = K[np.ix_(s_idx, s_idx)]
    K_ss_inv_K_sm = np.linalg.solve(K_ss, K_sm)
    K_r = K_mm - K_ms @ K_ss_inv_K_sm
    T = np.zeros((n, len(master_dofs)))
    T[m_idx, :] = np.eye(len(master_dofs))
    T[s_idx, :] = -K_ss_inv_K_sm
    return K_r, T


# ── ONNX surrogate (inference only) ──────────────────────────────────────

_ONNX_FILENAMES = {
    "horizontal_force_N": "mooring_surrogate_fx.onnx",
    "vertical_force_N":   "mooring_surrogate_fz.onnx",
    "fairlead_tension_N": "mooring_surrogate_t.onnx",
}
_METADATA_FILE = "surrogate_metadata.json"


class OnnxSurrogate:
    def __init__(self, sessions: dict, y_scale: float = 1.0):
        self.sessions = sessions
        self._y_scale = y_scale

    def predict(self, horizontal_offset: float,
                pretension_factor: float = 1.0,
                water_depth: float = 200.0) -> dict:
        x = np.array([[horizontal_offset, pretension_factor, water_depth]], dtype=np.float32)
        return {
            t: float(s.run(None, {"input": x})[0].ravel()[0]) * self._y_scale
            for t, s in self.sessions.items()
        }


def load_onnx_surrogate_from_dir(data_dir: str = "data") -> OnnxSurrogate:
    paths = {t: os.path.join(data_dir, f) for t, f in _ONNX_FILENAMES.items()}
    y_scale = 1.0
    meta = os.path.join(data_dir, _METADATA_FILE)
    if os.path.exists(meta):
        with open(meta) as f:
            y_scale = json.load(f).get("y_scale", 1.0)
    sessions = {t: rt.InferenceSession(p, providers=["CPUExecutionProvider"])
                for t, p in paths.items()}
    return OnnxSurrogate(sessions, y_scale=y_scale)


# ── Model comparison ──────────────────────────────────────────────────────

def _guyan_predict(K_r: np.ndarray, master_dofs: list, query_offset: float,
                   nominal_offset: float, f_nominal: tuple = (0.0, 0.0)) -> dict:
    # Proper static condensation: prescribe fairlead x (the offset change) and the
    # fixed anchor, leave interior master nodes free so the line re-sags; the fairlead
    # reaction + nominal force is the absolute tension. Holding the interior fixed
    # instead measures local axial stretch (~EA) → meganewton garbage over ±10 m.
    n = len(master_dofs)
    dof = n // 5
    presc = [0, 1, 2, n - 3, n - 2, n - 1]
    free = list(range(3, n - 3))
    up = np.zeros(len(presc))
    up[3] = query_offset - nominal_offset
    u = np.zeros(n)
    u[presc] = up
    u[free] = np.linalg.solve(K_r[np.ix_(free, free)], -K_r[np.ix_(free, presc)] @ up)
    r = K_r @ u
    fx = f_nominal[0] + float(r[-dof])
    fz = f_nominal[1] + float(r[-dof + 2])
    return {"horizontal_force_N": fx, "vertical_force_N": fz,
            "fairlead_tension_N": float(np.hypot(fx, fz))}


def _build_guyan_from_fem(nominal_offset: float = 785.7, n_elements: int = 20) -> tuple:
    from fem.mooring_fem import MooringFEM
    cfg = OC4Mooring
    fem_solver = MooringFEM(cfg, n_elements=n_elements)
    res_nom = fem_solver.solve(horizontal_offset=nominal_offset)
    f_nominal = (res_nom["horizontal_force_N"], res_nom["vertical_force_N"])
    K = fem_solver.get_stiffness_matrix()
    n_nodes = n_elements + 1
    dof_per_node = K.shape[0] // n_nodes
    # 5 master nodes at the line quartiles: 0, 25, 50, 75, 100 % of arc length
    node_indices = sorted({round(q) for q in np.linspace(0, n_nodes - 1, 5)})
    master_dofs = [d for nd in node_indices
                   for d in range(dof_per_node * nd, dof_per_node * nd + dof_per_node)]
    K_r, _ = guyan_reduce(K, master_dofs)
    return K_r, master_dofs, f_nominal


def compare_all_methods(horizontal_offsets: np.ndarray,
                        nominal_offset: float = 785.7,
                        n_fem_elements: int = 20,
                        onnx_data_dir: str = "data") -> pd.DataFrame:
    cfg = OC4Mooring
    w = cfg.mass_per_length * cfg.gravity
    onnx_model = load_onnx_surrogate_from_dir(onnx_data_dir)

    fem = K_r = master_dofs_cache = None
    f_nominal_guyan = (0.0, 0.0)
    try:
        from fem.mooring_fem import MooringFEM
        fem = MooringFEM(cfg, n_elements=n_fem_elements)
        K_r, master_dofs_cache, f_nominal_guyan = _build_guyan_from_fem(nominal_offset, n_fem_elements)
    except Exception:  # noqa: BLE001, S110 -- dolfinx unavailable (no Docker); FEM/Guyan columns become NaN below
        pass

    records = []
    for offset in horizontal_offsets:
        row = {"horizontal_offset": float(offset)}

        t0 = time.perf_counter()
        try:
            anl = solve_catenary(offset, abs(cfg.fairlead_depth - cfg.anchor_depth),
                                 cfg.unstretched_length, w)
            row["analytical_tension_N"] = anl["fairlead_tension"]
            row["analytical_fx_N"] = anl["horizontal_tension"]
            row["analytical_fz_N"] = float(np.sqrt(
                max(anl["fairlead_tension"]**2 - anl["horizontal_tension"]**2, 0.0)))
        except Exception:  # noqa: BLE001 -- catenary solve can fail in several ways; NaN plots as a gap
            row["analytical_tension_N"] = row["analytical_fx_N"] = row["analytical_fz_N"] = float("nan")
        row["analytical_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        if fem is not None:
            r = fem.solve(horizontal_offset=offset)
            if r["converged"]:
                row["fem_tension_N"] = r["fairlead_tension_N"]
                row["fem_fx_N"] = r["horizontal_force_N"]
                row["fem_fz_N"] = r["vertical_force_N"]
            else:
                row["fem_tension_N"] = row["fem_fx_N"] = row["fem_fz_N"] = float("nan")
        else:
            row["fem_tension_N"] = row["fem_fx_N"] = row["fem_fz_N"] = float("nan")
        row["fem_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        if K_r is not None:
            g = _guyan_predict(K_r, master_dofs_cache, offset, nominal_offset, f_nominal_guyan)
            row["guyan_tension_N"] = g["fairlead_tension_N"]
            row["guyan_fx_N"] = g["horizontal_force_N"]
            row["guyan_fz_N"] = g["vertical_force_N"]
        else:
            row["guyan_tension_N"] = row["guyan_fx_N"] = row["guyan_fz_N"] = float("nan")
        row["guyan_ms"] = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        o = onnx_model.predict(offset, 1.0, 200.0)
        row["onnx_tension_N"] = o["fairlead_tension_N"]
        row["onnx_fx_N"] = o["horizontal_force_N"]
        row["onnx_fz_N"] = o["vertical_force_N"]
        row["onnx_ms"] = (time.perf_counter() - t0) * 1000

        records.append(row)

    return pd.DataFrame(records)


# ── Blog helpers ──────────────────────────────────────────────────────────

def catenary_shape(horizontal_tension: float, w: float, seabed_length: float,
                   suspended_length: float, anchor_z: float = -200.0,
                   n_pts: int = 200) -> tuple[np.ndarray, np.ndarray]:
    H, L_s = horizontal_tension, suspended_length
    n_sb = max(2, int(n_pts * seabed_length / (seabed_length + L_s + 1e-9)))
    n_sus = n_pts - n_sb + 1
    x_sb = np.linspace(0.0, seabed_length, n_sb)
    z_sb = np.full(n_sb, anchor_z)
    s = np.linspace(0.0, L_s, n_sus)
    x_sus = seabed_length + (H / w) * np.arcsinh(w * s / H)
    z_sus = anchor_z + np.sqrt((H / w) ** 2 + s ** 2) - H / w
    return np.concatenate([x_sb, x_sus[1:]]), np.concatenate([z_sb, z_sus[1:]])


def export_plotly_gif(fig, output_path: str, fps: int = 8) -> None:
    try:
        import plotly.graph_objects as go
        import plotly.io as pio
        from PIL import Image
    except ImportError as exc:
        raise ImportError("export_plotly_gif requires kaleido and Pillow.") from exc

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    tmp_dir = os.path.join(os.path.dirname(os.path.abspath(output_path)), "_frames_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    frame_paths = []
    for i, frame in enumerate(fig.frames):
        p = os.path.join(tmp_dir, f"frame_{i:03d}.png")
        fig_f = go.Figure(data=frame.data, layout=fig.layout)
        fig_f.update_layout(title=frame.name or fig.layout.title.text,
                             showlegend=fig.layout.showlegend)
        pio.write_image(fig_f, p, width=900, height=500)
        frame_paths.append(p)

    if not frame_paths:
        raise ValueError("fig.frames is empty.")

    imgs = [Image.open(p) for p in frame_paths]
    imgs[0].save(output_path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 / fps), loop=0)
    for p in frame_paths:
        os.remove(p)
    os.rmdir(tmp_dir)
