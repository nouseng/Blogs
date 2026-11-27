# The Operating Simulation Remembers

Companion code for
[**A Digital Twin Needs a Memory**](post-3-data-backbone.md).

Post 2 put the Modelica FMU inside a Modbus operating loop. Post 3 keeps that
simulation application and adds a data backbone: every completed tick is
published to a single-node Redpanda broker, consumed by a separate sink,
and stored in a QuestDB WAL table with replay-safe deduplication.

This remains a laptop-scale prototype. It is not a synchronized operational
twin and has no physical asset connection, high availability, authentication,
TLS, alarm handling, backfill, or FMU state recovery.

## Run it

Allocate at least 4 GB to Docker, then:

```bash
docker compose up --build
```

- Plant console: <http://localhost:8080>
- QuestDB console: <http://localhost:9000>
- External Kafka endpoint: `localhost:19092`

Move a setpoint in the plant console, then run this in QuestDB:

```sql
SELECT t_wall, t_sim_s, P_it, T_amb, Q_sold, P_grid
FROM plant_ticks
ORDER BY t_wall DESC
LIMIT 20;
```

At 6× simulation speed, one 30-second FMU step appears about every five wall
seconds.

## Time and replay contract

Each `TickEvent` carries:

- `event_id = run_id:step`
- `t_sim_s`, the FMU's deterministic simulation time
- `t_wall_utc`, the UTC event time
- all `PlantInputs` and `PlantOutputs`
- price, feed-source labels, and `schema_version=1`

The sink commits its Kafka offset only after QuestDB accepts the row.
`DEDUP UPSERT KEYS(t_wall, event_id)` makes a replay idempotent.

## Optional live feeds

The reproducible default uses synthetic IT load, weather, and price. To use
current Stockholm weather from Open-Meteo:

```bash
LIVE_FEEDS=1 docker compose up --build
```

The price adapter accepts a configurable JSON endpoint:

```bash
LIVE_FEEDS=1 \
PRICE_FEED_URL=https://example.invalid/current \
PRICE_FEED_FIELD=data.se3_eur_mwh \
PRICE_FEED_TOKEN=optional-bearer-token \
docker compose up --build
```

No public Nord Pool endpoint is implied. Configure a source you are licensed
to use. Failed refreshes retain the last accepted value, and the default
synthetic value is used until the first live value arrives.

## What's in here

```text
console/       NiceGUI web page + Modbus client
gateway/       Modbus TCP server and write arbiter
orchestrator/  FMU loop, feed adapters, event schema, Kafka producer
sink/          Kafka consumer + QuestDB writer
contracts/     plant signal and register contracts
images/        article figures (tick order, feed timing, QuestDB console)
compose.yml    six-service local stack
```

Redpanda is deliberately a single broker capped at 512 MB. QuestDB and
Redpanda use named volumes. `docker compose down` preserves them, while
`docker compose down -v` removes the stored demo history.

## License

MIT, in [LICENSE](LICENSE).
