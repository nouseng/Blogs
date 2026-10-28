"""NiceGUI operator console for the Post 2 heat-recovery twin prototype."""

import os
import time
from datetime import datetime, timezone

from nicegui import app, ui
from pymodbus.client import ModbusTcpClient

from console.energy import SessionEnergy
from console.modbus_io import (
    network_flow_lps,
    read_tile_values,
    write_q_hp_set,
    write_u_prod,
    write_y_chg,
    write_y_dry,
)
from contracts.signals import WRITE_BOUNDS

GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "gateway")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "5020"))
SIM_SPEED_K = float(os.environ.get("SIM_SPEED_K", "6.0"))

client = ModbusTcpClient(GATEWAY_HOST, port=GATEWAY_PORT)
app.add_static_files("/static", "console/static")

# signal -> label, unit, register, plain-language interpretation, icon, colour
READING_INFO = {
    "T_amb": (
        "Ambient Temperature", "°C", 40014,
        "Outdoor temperature used for the current FMU step",
        "device_thermostat", "blue-grey",
    ),
    "T_tank_top": (
        "Tank Temperature", "°C", 40008,
        "Accumulator temperature; determines which delivery products the stored heat can serve",
        "propane_tank", "deep-orange",
    ),
    "Q_sold": (
        "Heat Export", "kW thermal", 40002,
        "Thermal power entering the district-heating network now",
        "local_fire_department", "red",
    ),
    "P_grid": (
        "Electricity Import", "kW electric", 40007,
        "Total site demand currently bought from the electricity grid",
        "bolt", "blue",
    ),
    "COP_hp": (
        "Current Heat-Pump COP", "thermal / electric", 40012,
        "Heat delivered per unit of compressor electricity; shown as Off when the pump is inactive",
        "speed", "green",
    ),
}

# Only the heat-pump condenser-duty command is genuinely continuous.
HEAT_PUMP_CONTROL = (
    "Heat-Pump Output", "MW thermal", 40102,
    "Requested condenser heat from 0 to 8 MW. Electrical input is lower and depends on the current COP.",
    "heat_pump", "deep-orange", write_q_hp_set, 0.05,
)

ACCUMULATOR_OPTIONS = {-1.0: "Discharge", 0.0: "Idle", 1.0: "Charge"}
DRY_COOLER_OPTIONS = {0.0: "Off", 0.5: "50%", 1.0: "Full"}
PRODUCT_OPTIONS = {0: "No export", 1: "Retur", 2: "Inblandning", 3: "Prima"}


def _stat_tile(label, unit, register, meaning, icon, color, source=None):
    with ui.column().classes("items-center gap-1 px-2"):
        ui.icon(icon, color=color).classes("text-3xl")
        ui.label(label).classes("text-sm font-medium text-center")
        value = ui.label("—").classes("text-3xl font-bold text-center")
        ui.label(unit).classes("text-xs text-gray-500 text-center")
        source_line = (
            f"Register {register} · {meaning}"
            if source is None
            else f"{source} · {meaning}"
        )
        ui.label(source_line).classes(
            "text-xs text-gray-400 text-center max-w-52"
        )
    return value


def _energy_tile(label, icon, color, value_color):
    with ui.column().classes("items-center gap-1 px-2"):
        ui.icon(icon, color=color).classes("text-3xl")
        ui.label(label).classes("text-sm font-medium text-center")
        value = ui.label("0.0").classes(f"text-3xl font-bold text-center {value_color}")
        ui.label("kWh").classes("text-xs text-gray-500 text-center")
        ui.label("Accumulated since this dashboard opened").classes(
            "text-xs text-gray-400 text-center max-w-52"
        )
    return value


def _build_overview_card():
    tiles = {}
    with ui.card().classes("w-full"):
        ui.label(
            "Current Plant Readings"
        ).classes("text-lg font-semibold")
        with ui.element("div").classes(
            "grid grid-cols-2 md:grid-cols-4 "
            "gap-x-5 gap-y-5 w-full pt-2"
        ):
            for key, data in READING_INFO.items():
                tiles[key] = _stat_tile(*data)
            # The derived flow tile sits beside the direct register reads.
            tiles["flow"] = _stat_tile(
                "Network Water Flow", "l/s", None,
                "Volume delivered to the district network, derived from heat export and the delivery and return temperatures.",
                "water_drop", "light-blue", source="derived",
            )
            electricity = _energy_tile(
                "Electricity Bought", "electric_meter", "blue", "text-blue-600"
            )
            heat = _energy_tile(
                "Heat Sold", "local_fire_department", "red", "text-red-600"
            )
        with ui.row().classes(
            "w-full items-end justify-between gap-x-6 gap-y-1 flex-wrap "
            "border-t border-gray-200 pt-2 mt-1"
        ):
            with ui.column().classes("gap-0"):
                started = ui.label(
                    "Starts with the first valid plant reading"
                ).classes("text-xs text-gray-500")
                ui.label(
                    "Demo totals since this page opened. Integrated over simulated time. "
                    "Reset on reload."
                ).classes("text-xs text-gray-400")
            elapsed = ui.label("0.0 simulated minutes counted").classes(
                "text-xs text-gray-400"
            )
        energy_labels = {
            "started": started,
            "electricity": electricity,
            "heat": heat,
            "elapsed": elapsed,
        }
    return tiles, energy_labels


def _control_heading(icon, color, label, register):
    with ui.row().classes("items-center gap-2"):
        ui.icon(icon, color=color).classes("text-2xl")
        ui.label(label).classes("font-medium")
        ui.label(f"reg {register}").classes("text-xs text-gray-400")


def _build_controls_card(client):
    with ui.card().classes("w-full"):
        ui.label("Manual Plant Controls").classes("text-lg font-semibold")
        ui.label(
            "This prototype has no automatic controller; every command below is written by the operator."
        ).classes("text-xs text-gray-500 max-w-sm")

        label, unit, register, meaning, icon, color, writer, step = HEAT_PUMP_CONTROL
        _control_heading(icon, color, f"{label} ({unit})", register)
        slider = ui.slider(
            min=WRITE_BOUNDS["Q_hp_set"][0] / 1000.0,
            max=WRITE_BOUNDS["Q_hp_set"][1] / 1000.0,
            step=step,
            value=0.0,
            on_change=lambda e: writer(client, e.value * 1000.0),
        )
        ui.label().bind_text_from(
            slider, "value", backward=lambda value: f"{value:.2f} MW thermal requested"
        )
        ui.label(meaning).classes("text-xs text-gray-500 max-w-sm mb-3")

        _control_heading("battery_charging_full", "amber", "Accumulator Mode", 40104)
        ui.toggle(
            ACCUMULATOR_OPTIONS,
            value=0.0,
            on_change=lambda e: write_y_chg(client, e.value),
        ).props("spread").classes("w-full")
        ui.label(
            "Charge diverts current heat production into the tank. Idle bypasses production to the "
            "network. Discharge adds tank output only when its temperature is high enough."
        ).classes("text-xs text-gray-500 max-w-sm mb-3")

        _control_heading("air", "cyan", "Dry-Cooler Capacity", 40103)
        ui.toggle(
            DRY_COOLER_OPTIONS,
            value=1.0,
            on_change=lambda e: write_y_dry(client, e.value),
        ).props("spread").classes("w-full")
        ui.label(
            "Limits available free-cooling capacity. Any rejection duty above the selected stage is "
            "handled by mechanical cooling and increases electricity import."
        ).classes("text-xs text-gray-500 max-w-sm mb-3")

        _control_heading("sell", "green", "District-Heating Product", 40101)
        ui.select(
            PRODUCT_OPTIONS,
            value=0,
            on_change=lambda e: write_u_prod(client, e.value),
        ).classes("w-full")
        ui.label(
            "Retur has the lowest temperature requirement. Inblandning and Prima require progressively "
            "hotter delivery and usually more heat-pump power."
        ).classes("text-xs text-gray-500 max-w-sm")


def _build_explainer():
    with ui.card().classes("w-full"):
        with ui.expansion(
            "How one plant update moves through the system",
            caption=(
                "console polls every 1 s; orchestrator advances 30 simulated s "
                "about every 5 wall-clock s"
            ),
            icon="help_outline",
        ).classes("w-full"):
            ui.image("/static/post2-tick-order.gif").classes("w-full max-w-3xl mx-auto")
            ui.label(
                "A command waits in the Modbus gateway until the orchestrator's next tick. "
                "The FMU advances, new readings are published, and the console picks them "
                "up on its independent polling clock."
            ).classes("text-sm text-gray-500 max-w-3xl mx-auto")


@ui.page("/")
def index():
    with ui.header().classes("items-center justify-between px-4 text-white").style(
        "background-color: #1e293b"
    ):
        with ui.row().classes(
            "w-full max-w-[1800px] mx-auto items-center justify-between no-wrap"
        ):
            with ui.column().classes("gap-0"):
                ui.label("Heat-Recovery Twin Prototype").classes("text-2xl")
                ui.label(
                    "Physics-backed FMU · manual controls · Modbus TCP operating loop"
                ).classes("text-xs opacity-80")
            badge = ui.badge("connecting…", color="grey")

    with ui.column().classes("w-full max-w-[1800px] mx-auto p-3 gap-3"):
        with ui.element("div").classes(
            "w-full grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_420px] "
            "gap-3 items-start"
        ):
            with ui.column().classes("w-full gap-3"):
                readings, energy_labels = _build_overview_card()
                _build_explainer()
            _build_controls_card(client)
        error_label = ui.label().classes("text-xs text-red-500")

    session_energy = None

    def refresh():
        nonlocal session_energy
        if not client.connected:
            client.connect()
        try:
            values = read_tile_values(client)
            readings["T_amb"].set_text(f"{values['T_amb']:.1f}")
            readings["T_tank_top"].set_text(f"{values['T_tank_top']:.1f}")
            readings["Q_sold"].set_text(f"{values['Q_sold']:.0f}")
            readings["P_grid"].set_text(f"{values['P_grid']:.0f}")
            readings["COP_hp"].set_text(
                "Off" if values["COP_hp"] <= 0.0 else f"{values['COP_hp']:.2f}"
            )
            readings["flow"].set_text(
                f"{network_flow_lps(values['Q_sold'], values['T_net_del'], values['T_net_ret']):.0f}"
            )

            if session_energy is None:
                session_energy = SessionEnergy(
                    started_at_utc=datetime.now(timezone.utc),
                    speed_factor=SIM_SPEED_K,
                )
                energy_labels["started"].set_text(
                    "Started " + session_energy.started_at_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
                )
            session_energy.sample(
                now_s=time.monotonic(),
                p_grid_kw=values["P_grid"],
                q_sold_kw=values["Q_sold"],
            )
            energy_labels["electricity"].set_text(
                f"{session_energy.electricity_bought_kwh:,.1f}"
            )
            energy_labels["heat"].set_text(f"{session_energy.heat_sold_kwh:,.1f}")
            energy_labels["elapsed"].set_text(
                f"{session_energy.simulated_elapsed_s / 60.0:,.1f} simulated minutes counted"
            )

            badge.set_text("connected")
            badge.props("color=green")
            error_label.set_text("")
        except Exception as exc:  # noqa: BLE001 - connection state belongs in the UI
            if session_energy is not None:
                session_energy.pause()
            badge.set_text("gateway unreachable")
            badge.props("color=red")
            error_label.set_text(str(exc))

    ui.timer(1.0, refresh)


ui.run(host="0.0.0.0", port=8080, title="Heat-Recovery Twin Prototype")
