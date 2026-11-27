"""Consume Redpanda tick events and persist them idempotently in QuestDB."""

import os
import time

from orchestrator.events import TickEvent


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS plant_ticks (
    t_wall TIMESTAMP,
    event_id SYMBOL,
    run_id SYMBOL,
    schema_version INT,
    step LONG,
    t_sim_s DOUBLE,
    weather_source SYMBOL,
    price_source SYMBOL,
    price_eur_mwh DOUBLE,
    P_it DOUBLE,
    T_amb DOUBLE,
    T_net_sup DOUBLE,
    T_net_ret DOUBLE,
    u_prod DOUBLE,
    Q_hp_set DOUBLE,
    y_dry DOUBLE,
    y_chg DOUBLE,
    Q_dem DOUBLE,
    Q_hall DOUBLE,
    Q_sold DOUBLE,
    Q_dump DOUBLE,
    P_hp DOUBLE,
    P_dry DOUBLE,
    P_air DOUBLE,
    P_grid DOUBLE,
    T_tank_top DOUBLE,
    T_tank_bot DOUBLE,
    T_liq_sup DOUBLE,
    T_liq_ret DOUBLE,
    COP_hp DOUBLE,
    T_net_del DOUBLE
) TIMESTAMP(t_wall)
PARTITION BY DAY WAL
DEDUP UPSERT KEYS(t_wall, event_id);
""".strip()


class QuestDBWriter:
    """Create the table once and write events with their original wall time."""

    def __init__(
        self,
        http_url: str,
        *,
        sender=None,
        http_client=None,
        timestamp_factory=None,
    ) -> None:
        if http_client is None:
            import httpx

            http_client = httpx.Client(timeout=10.0)
        self._http = http_client
        self._http_url = http_url.rstrip("/")
        self._sender = sender
        self._sender_context = None
        self._timestamp_factory = timestamp_factory

    def start(self) -> None:
        """Create the WAL+dedup table and connect the ingestion sender."""
        response = self._http.get(
            f"{self._http_url}/exec",
            params={"query": CREATE_TABLE_SQL},
        )
        response.raise_for_status()
        if self._sender is None:
            from questdb import Sender, TimestampNanos

            addr = self._http_url.removeprefix("http://").removeprefix(
                "https://"
            )
            self._sender_context = Sender.from_conf(
                f"http::addr={addr};"
            )
            self._sender = self._sender_context.__enter__()
            self._timestamp_factory = TimestampNanos

    def write(self, event: TickEvent) -> None:
        """Write one event. Replays replace, rather than duplicate, a row."""
        if self._sender is None:
            raise RuntimeError("QuestDBWriter.start() must be called first")
        timestamp_factory = self._timestamp_factory or (lambda value: value)
        columns = {
            "schema_version": event.schema_version,
            "step": event.step,
            "t_sim_s": event.t_sim_s,
            "price_eur_mwh": event.price_eur_mwh,
            **vars(event.inputs),
            **vars(event.outputs),
        }
        self._sender.row(
            "plant_ticks",
            symbols={
                "event_id": event.event_id,
                "run_id": event.run_id,
                "weather_source": event.weather_source,
                "price_source": event.price_source,
            },
            columns=columns,
            at=timestamp_factory(event.wall_time_ns),
        )
        self._sender.flush()

    def close(self) -> None:
        """Close the sender and HTTP client."""
        if self._sender_context is not None:
            self._sender_context.__exit__(None, None, None)
        close = getattr(self._http, "close", None)
        if close is not None:
            close()


def store_and_commit(message, writer: QuestDBWriter, consumer) -> None:
    """Commit the Kafka offset only after QuestDB accepts the event."""
    writer.write(TickEvent.from_json(message.value))
    consumer.commit()


def run_forever() -> None:
    """Run the at-least-once Kafka-to-QuestDB sink."""
    from kafka import KafkaConsumer

    bootstrap = os.environ.get(
        "KAFKA_BOOTSTRAP_SERVERS",
        "redpanda:9092",
    )
    topic = os.environ.get(
        "KAFKA_TICK_TOPIC",
        "dc2dh.plant-ticks.v1",
    )
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id="dc2dh-questdb-v1",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    writer = QuestDBWriter(
        os.environ.get("QUESTDB_HTTP_URL", "http://questdb:9000")
    )
    while True:
        try:
            writer.start()
            break
        except Exception:
            time.sleep(1.0)
    try:
        for message in consumer:
            store_and_commit(message, writer, consumer)
    finally:
        writer.close()
        consumer.close()


if __name__ == "__main__":
    run_forever()
