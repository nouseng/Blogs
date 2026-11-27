"""Kafka/Redpanda publisher for versioned tick events."""

from typing import Protocol

from orchestrator.events import TickEvent


class EventPublisher(Protocol):
    """Publisher boundary used by the orchestrator and tests."""

    def publish(self, event: TickEvent) -> None:
        """Durably acknowledge one event or raise."""
        ...

    def close(self) -> None:
        """Flush and release resources."""
        ...


class KafkaTickPublisher:
    """Publish one keyed JSON event per completed plant tick."""

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        topic: str = "dc2dh.plant-ticks.v1",
        producer=None,
    ) -> None:
        if producer is None:
            from kafka import KafkaProducer

            producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                acks="all",
                retries=10,
                linger_ms=5,
            )
        self._producer = producer
        self._topic = topic

    def publish(self, event: TickEvent) -> None:
        """Wait for broker acknowledgement; never drop a failed event."""
        future = self._producer.send(
            self._topic,
            key=event.event_id.encode("utf-8"),
            value=event.to_json().encode("utf-8"),
        )
        future.get(timeout=10)

    def close(self) -> None:
        """Flush pending events before shutdown."""
        self._producer.flush(timeout=10)
        self._producer.close(timeout=10)
