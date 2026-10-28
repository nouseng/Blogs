"""Session-only energy accounting for the Post 2 web console."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SessionEnergy:
    """Integrate sampled powers over accelerated simulation time.

    The counter belongs to one dashboard session. It is deliberately not a
    historian and resets when the page reloads.
    """

    started_at_utc: datetime
    speed_factor: float
    electricity_bought_kwh: float = 0.0
    heat_sold_kwh: float = 0.0
    simulated_elapsed_s: float = 0.0
    _last_sample_s: float | None = None

    def sample(self, now_s: float, p_grid_kw: float, q_sold_kw: float) -> None:
        """Add one zero-order-hold interval ending at ``now_s``."""
        if self._last_sample_s is None:
            self._last_sample_s = now_s
            return

        wall_dt_s = max(0.0, now_s - self._last_sample_s)
        sim_dt_s = wall_dt_s * self.speed_factor
        self.electricity_bought_kwh += max(0.0, p_grid_kw) * sim_dt_s / 3600.0
        self.heat_sold_kwh += max(0.0, q_sold_kw) * sim_dt_s / 3600.0
        self.simulated_elapsed_s += sim_dt_s
        self._last_sample_s = now_s

    def pause(self) -> None:
        """Exclude a gateway-disconnection gap from the next interval."""
        self._last_sample_s = None
