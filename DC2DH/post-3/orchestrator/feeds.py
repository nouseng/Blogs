"""Synthetic fallback and opt-in live weather/price feed adapters."""

from dataclasses import dataclass
import logging
import math
import os
from typing import Protocol

from orchestrator.disturbance import generate_disturbance

LOGGER = logging.getLogger(__name__)


class ScalarFeed(Protocol):
    """A live source that returns one engineering-unit value."""

    source: str

    def read(self) -> float:
        """Fetch the current value."""
        ...


@dataclass(frozen=True)
class FeedSnapshot:
    """Disturbances and metadata used by one plant tick."""

    p_it_kw: float
    t_amb_c: float
    price_eur_mwh: float
    weather_source: str
    price_source: str


@dataclass(frozen=True)
class GateDecision:
    """Whether a sampled live value should replace the accepted value."""

    emit: bool
    reason: str | None
    value: float


class DebounceHeartbeat:
    """Suppress transient changes but refresh an unchanged value eventually."""

    def __init__(
        self,
        *,
        debounce_s: float,
        heartbeat_s: float,
        tolerance: float,
    ) -> None:
        self.debounce_s = debounce_s
        self.heartbeat_s = heartbeat_s
        self.tolerance = tolerance
        self.accepted: float | None = None
        self._candidate: float | None = None
        self._candidate_since_s: float | None = None
        self._last_emit_s: float | None = None

    def consider(self, value: float, now_s: float) -> GateDecision:
        """Apply initial/change/heartbeat timing to one sample."""
        if self.accepted is None:
            return self._accept(value, now_s, "initial")

        assert self._last_emit_s is not None
        if abs(value - self.accepted) <= self.tolerance:
            self._candidate = None
            self._candidate_since_s = None
            if now_s - self._last_emit_s >= self.heartbeat_s:
                return self._accept(self.accepted, now_s, "heartbeat")
            return GateDecision(False, None, self.accepted)

        if (
            self._candidate is None
            or abs(value - self._candidate) > self.tolerance
        ):
            self._candidate = value
            self._candidate_since_s = now_s
            return GateDecision(False, None, self.accepted)

        assert self._candidate_since_s is not None
        if now_s - self._candidate_since_s >= self.debounce_s:
            return self._accept(value, now_s, "change")

        return GateDecision(False, None, self.accepted)

    def _accept(
        self,
        value: float,
        now_s: float,
        reason: str,
    ) -> GateDecision:
        self.accepted = value
        self._candidate = None
        self._candidate_since_s = None
        self._last_emit_s = now_s
        return GateDecision(True, reason, value)


class OpenMeteoWeatherFeed:
    """Current Stockholm dry-bulb temperature from Open-Meteo."""

    source = "open-meteo"

    def __init__(self, client=None) -> None:
        if client is None:
            import httpx

            client = httpx.Client(timeout=5.0)
        self._client = client

    def read(self) -> float:
        """Fetch the current two-metre temperature in degrees Celsius."""
        response = self._client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 59.3293,
                "longitude": 18.0686,
                "current": "temperature_2m",
            },
        )
        response.raise_for_status()
        return float(response.json()["current"]["temperature_2m"])


class JsonPriceFeed:
    """Configurable JSON price endpoint, kept provider-neutral on purpose."""

    source = "http-price"

    def __init__(
        self,
        url: str,
        *,
        field: str = "price_eur_mwh",
        token: str | None = None,
        client=None,
    ) -> None:
        if client is None:
            import httpx

            client = httpx.Client(timeout=5.0)
        self._client = client
        self._url = url
        self._field = field
        self._headers = (
            {"Authorization": f"Bearer {token}"} if token else {}
        )

    def read(self) -> float:
        """Fetch a numeric value from a dot-separated JSON field path."""
        response = self._client.get(self._url, headers=self._headers)
        response.raise_for_status()
        value = response.json()
        for part in self._field.split("."):
            value = value[part]
        return float(value)


class SyntheticFeedProvider:
    """Deterministic fallback used by tests and the default demo."""

    def snapshot(self, t_sim_s: float, now_s: float) -> FeedSnapshot:
        """Return repeatable IT, weather, and price values."""
        del now_s
        p_it_kw, t_amb_c = generate_disturbance(t_sim_s)
        phase = 2.0 * math.pi * (t_sim_s % 86_400.0) / 86_400.0
        price = 55.0 + 20.0 * math.sin(phase - math.pi / 3.0)
        return FeedSnapshot(
            p_it_kw=p_it_kw,
            t_amb_c=t_amb_c,
            price_eur_mwh=price,
            weather_source="synthetic",
            price_source="synthetic",
        )


class LiveFeedProvider:
    """Poll live adapters slowly and retain the last accepted values."""

    def __init__(
        self,
        weather: ScalarFeed,
        price: ScalarFeed | None,
        *,
        refresh_s: float = 60.0,
        fallback: SyntheticFeedProvider | None = None,
    ) -> None:
        self._weather = weather
        self._price = price
        self._refresh_s = refresh_s
        self._fallback = fallback or SyntheticFeedProvider()
        self._next_refresh_s = float("-inf")
        self._weather_gate = DebounceHeartbeat(
            debounce_s=60.0,
            heartbeat_s=300.0,
            tolerance=0.2,
        )
        self._price_gate = DebounceHeartbeat(
            debounce_s=60.0,
            heartbeat_s=300.0,
            tolerance=0.01,
        )

    def snapshot(self, t_sim_s: float, now_s: float) -> FeedSnapshot:
        """Return accepted live values, falling back without inventing data."""
        fallback = self._fallback.snapshot(t_sim_s, now_s)
        if now_s >= self._next_refresh_s:
            self._next_refresh_s = now_s + self._refresh_s
            try:
                self._weather_gate.consider(self._weather.read(), now_s)
            except Exception as exc:
                LOGGER.warning("weather feed refresh failed: %s", exc)
            if self._price is not None:
                try:
                    self._price_gate.consider(self._price.read(), now_s)
                except Exception as exc:
                    LOGGER.warning("price feed refresh failed: %s", exc)

        weather_live = self._weather_gate.accepted
        price_live = self._price_gate.accepted
        return FeedSnapshot(
            p_it_kw=fallback.p_it_kw,
            t_amb_c=(
                weather_live
                if weather_live is not None
                else fallback.t_amb_c
            ),
            price_eur_mwh=(
                price_live
                if price_live is not None
                else fallback.price_eur_mwh
            ),
            weather_source=(
                self._weather.source
                if weather_live is not None
                else fallback.weather_source
            ),
            price_source=(
                self._price.source
                if self._price is not None and price_live is not None
                else fallback.price_source
            ),
        )


def build_feed_provider():
    """Build the reproducible default or opt-in live provider from env."""
    if os.environ.get("LIVE_FEEDS", "0").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return SyntheticFeedProvider()

    price_url = os.environ.get("PRICE_FEED_URL")
    price = (
        JsonPriceFeed(
            price_url,
            field=os.environ.get("PRICE_FEED_FIELD", "price_eur_mwh"),
            token=os.environ.get("PRICE_FEED_TOKEN"),
        )
        if price_url
        else None
    )
    return LiveFeedProvider(OpenMeteoWeatherFeed(), price)
