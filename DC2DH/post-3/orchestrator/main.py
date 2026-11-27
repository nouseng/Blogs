"""Orchestrator entry point: run the plant and publish every completed tick."""

from datetime import datetime, timezone
import os
import time
import uuid
from pymodbus.client import ModbusTcpClient
from orchestrator.events import TickEvent
from orchestrator.feeds import build_feed_provider
from orchestrator.streaming import KafkaTickPublisher
from orchestrator.tick import run_tick_snapshot
from orchestrator.fmu_plant import FMUPlantModel

DT_FMU_S = 30.0


class PymodbusClientAdapter:
    """Adapts pymodbus's client to the orchestrator.tick.ModbusIO protocol."""

    def __init__(self, client: ModbusTcpClient) -> None:
        """Args:
            client: Connected pymodbus TCP client to wrap.
        """
        self._client = client

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        """Args:
            address: Zero-based Modbus register address to start reading at.
            count: Number of consecutive registers to read.

        Returns:
            Raw register values as a list of ints.
        """
        result = self._client.read_holding_registers(address, count)
        if result.isError():
            raise RuntimeError(
                f"Modbus read failed at address {address}, count {count}: "
                f"{result}"
            )
        registers = getattr(result, "registers", None)
        if registers is None or len(registers) != count:
            raise RuntimeError(
                f"Modbus read at address {address} returned "
                f"{0 if registers is None else len(registers)} registers; "
                f"expected {count}"
            )
        return list(registers)

    def write_registers(self, address: int, values: list[int]) -> None:
        """Args:
            address: Zero-based Modbus register address to start writing at.
            values: Signed engineering-unit-scaled values to write; negative
                values are two's-complement encoded before the wire write.
        """
        # Modbus holding registers are unsigned 16-bit; some outputs (e.g.
        # sub-zero T_amb) are legitimately negative in engineering units.
        # P_grid is import-only and never negative (contracts/signals.py),
        # but nothing here assumes every signal is nonnegative, since the
        # next disturbance/output added to the map might be. Encode only
        # negative values as two's complement -- the in-memory fake IO
        # used by tick tests has no such constraint, so this only bites
        # with a real client. A positive value outside 0-65535 is not a
        # known-legitimate case (e.g. a runaway/unbounded plant state)
        # and is passed through unmodified so the real client's own
        # range check raises loudly, instead of being silently wrapped
        # into a plausible-looking but wrong reading.
        encoded_values = [v & 0xFFFF if v < 0 else v for v in values]
        result = self._client.write_registers(address, encoded_values)
        if result.isError():
            raise RuntimeError(
                f"Modbus write failed at address {address}, "
                f"count {len(encoded_values)}: {result}"
            )


def run_forever(
    host: str = "gateway",
    port: int = 5020,
    dt_s: float = DT_FMU_S,
    k: float = 6.0,
    *,
    publisher=None,
    feed_provider=None,
    run_id: str | None = None,
) -> None:
    """Connect to the gateway and run ticks forever at wall-clock pace.

    k = speed factor (sim-seconds per wall-second). k=6 -> one 30s
    tick every 5 wall-seconds, watchable live in the console.

    Args:
        host: Gateway hostname.
        port: Gateway Modbus TCP port.
        dt_s: Simulated seconds advanced per tick.
        k: Speed factor; wall-seconds per tick = dt_s / k.
        publisher: Optional EventPublisher override for tests.
        feed_provider: Optional feed provider override for tests.
        run_id: Stable identity for this simulation run.
    """
    client = ModbusTcpClient(host, port=port)
    while not client.connect():
        time.sleep(1.0)

    io = PymodbusClientAdapter(client)
    plant = FMUPlantModel()
    publisher = publisher or KafkaTickPublisher(
        os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092"),
        topic=os.environ.get(
            "KAFKA_TICK_TOPIC",
            "dc2dh.plant-ticks.v1",
        ),
    )
    feed_provider = feed_provider or build_feed_provider()
    run_id = run_id or os.environ.get("RUN_ID") or uuid.uuid4().hex
    t_sim_s = 0.0
    step = 0
    wall_dt = dt_s / k

    try:
        while True:
            t_wall = datetime.now(timezone.utc)
            feed = feed_provider.snapshot(t_sim_s, t_wall.timestamp())
            snapshot = run_tick_snapshot(
                plant,
                io,
                dt_s,
                t_sim_s,
                disturbance=(feed.p_it_kw, feed.t_amb_c),
            )
            event = TickEvent.from_snapshot(
                run_id=run_id,
                step=step,
                t_sim_s=t_sim_s,
                t_wall_utc=t_wall,
                price_eur_mwh=feed.price_eur_mwh,
                weather_source=feed.weather_source,
                price_source=feed.price_source,
                snapshot=snapshot,
            )
            publisher.publish(event)
            step += 1
            t_sim_s += dt_s
            time.sleep(wall_dt)
    finally:
        publisher.close()
        client.close()


if __name__ == "__main__":
    run_forever(
        host=os.environ.get("GATEWAY_HOST", "gateway"),
        port=int(os.environ.get("GATEWAY_PORT", "5020")),
        k=float(os.environ.get("SIM_SPEED_K", "6.0")),
    )
