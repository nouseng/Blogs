"""Versioned event contract for persisted plant ticks."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any

from contracts.signals import PlantInputs, PlantOutputs
from orchestrator.tick import TickSnapshot


@dataclass(frozen=True)
class TickEvent:
    """One immutable simulation step, ready for Kafka and QuestDB."""

    schema_version: int
    event_id: str
    run_id: str
    step: int
    t_sim_s: float
    t_wall_utc: datetime
    price_eur_mwh: float
    weather_source: str
    price_source: str
    inputs: PlantInputs
    outputs: PlantOutputs

    @classmethod
    def from_snapshot(
        cls,
        *,
        run_id: str,
        step: int,
        t_sim_s: float,
        t_wall_utc: datetime,
        price_eur_mwh: float,
        weather_source: str,
        price_source: str,
        snapshot: TickSnapshot,
    ) -> "TickEvent":
        """Build a stable event identity from run and step."""
        if t_wall_utc.tzinfo is None:
            raise ValueError("t_wall_utc must be timezone-aware")
        return cls(
            schema_version=1,
            event_id=f"{run_id}:{step}",
            run_id=run_id,
            step=step,
            t_sim_s=t_sim_s,
            t_wall_utc=t_wall_utc.astimezone(timezone.utc),
            price_eur_mwh=price_eur_mwh,
            weather_source=weather_source,
            price_source=price_source,
            inputs=snapshot.inputs,
            outputs=snapshot.outputs,
        )

    @property
    def wall_time_ns(self) -> int:
        """Wall-clock timestamp as integer nanoseconds without float drift."""
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = self.t_wall_utc - epoch
        return (
            delta.days * 86_400_000_000_000
            + delta.seconds * 1_000_000_000
            + delta.microseconds * 1_000
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-safe wire representation."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "step": self.step,
            "t_sim_s": self.t_sim_s,
            "t_wall_utc": self.t_wall_utc.isoformat(),
            "price_eur_mwh": self.price_eur_mwh,
            "weather_source": self.weather_source,
            "price_source": self.price_source,
            "inputs": asdict(self.inputs),
            "outputs": asdict(self.outputs),
        }

    def to_json(self) -> str:
        """Serialize deterministically for repeatable Kafka payloads."""
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TickEvent":
        """Rebuild an event consumed from Kafka."""
        if data.get("schema_version") != 1:
            raise ValueError(
                f"unsupported schema_version={data.get('schema_version')}"
            )
        return cls(
            schema_version=1,
            event_id=str(data["event_id"]),
            run_id=str(data["run_id"]),
            step=int(data["step"]),
            t_sim_s=float(data["t_sim_s"]),
            t_wall_utc=datetime.fromisoformat(
                str(data["t_wall_utc"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc),
            price_eur_mwh=float(data["price_eur_mwh"]),
            weather_source=str(data["weather_source"]),
            price_source=str(data["price_source"]),
            inputs=PlantInputs(**data["inputs"]),
            outputs=PlantOutputs(**data["outputs"]),
        )

    @classmethod
    def from_json(cls, payload: bytes | str) -> "TickEvent":
        """Decode a Kafka value."""
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return cls.from_dict(json.loads(payload))
