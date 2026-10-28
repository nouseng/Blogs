"""Modbus datastore: single write-arbitration authority plus the read/write register split."""

from dataclasses import dataclass
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusSlaveContext,
    ModbusServerContext,
)
from contracts.signals import READ_REGISTERS, WRITE_REGISTERS, WRITE_BOUNDS

# Derive the size from the contract so adding a signal cannot silently leave
# the final register outside the Modbus datastore.
READ_BLOCK_SIZE = max(address for address, _scale in READ_REGISTERS.values()) + 1
WRITE_BLOCK_SIZE = 8   # covers addresses 100-103 with headroom
WRITE_BLOCK_BASE = 100


@dataclass
class WriteLogEntry:
    """One recorded write to a holding register.

    Attributes:
        address: Zero-based Modbus register address written.
        raw_value: Raw value requested before any clamp was applied.
        accepted: Always True today; reserved for future write rejection.
        clamped: Whether the requested value was clamped to WRITE_BOUNDS.
        source: Write authority tag (e.g. "manual").
    """

    address: int
    raw_value: int
    accepted: bool
    clamped: bool
    source: str


def _register_name_for_address(address: int) -> str | None:
    """Look up the signal name that owns a given write-register address.

    Args:
        address: Zero-based Modbus register address.

    Returns:
        The matching name from WRITE_REGISTERS, or None if no signal owns it.
    """
    for name, (addr, _scale) in WRITE_REGISTERS.items():
        if addr == address:
            return name
    return None


class ArbitratedWriteBlock(ModbusSequentialDataBlock):
    """Single write authority on the field bus (architecture doc §2, §6.3).
    Every write is clamped to its physical bounds and logged. This prototype
    has exactly one write source ('manual', the console); an 'auto' source
    can join once a controller exists."""

    log: list

    def __init__(self, source: str = "manual") -> None:
        """Args:
            source: Write authority tag recorded on every WriteLogEntry.
        """
        # Every register defaults to 0 except y_chg, which decodes 0 as
        # full discharge (orchestrator/tick.py). Defaulting its raw value
        # to 500 (idle) keeps a freshly started stack from draining the
        # accumulator before an operator ever touches a control.
        # y_dry defaults to full duty (1000 raw = 1.0 engineering): raw 0
        # means fans off, which forces 100% mechanical cooling the
        # instant the plant model reads it (StockholmPod.mo).
        initial_values = [0] * WRITE_BLOCK_SIZE
        y_chg_addr, _ = WRITE_REGISTERS["y_chg"]
        initial_values[y_chg_addr - WRITE_BLOCK_BASE] = 500
        y_dry_addr, y_dry_scale = WRITE_REGISTERS["y_dry"]
        initial_values[y_dry_addr - WRITE_BLOCK_BASE] = int(1.0 * y_dry_scale)
        super().__init__(WRITE_BLOCK_BASE, initial_values)
        self.source = source
        self.log = []

    def setValues(self, address: int, values: list[int]) -> None:
        """Clamp incoming register values to their physical bounds, log the
        write, then apply the (possibly clamped) values.

        Args:
            address: Zero-based Modbus register address of the first value.
            values: Raw register values to write, starting at address.
        """
        clamped_values = []
        for offset, raw_value in enumerate(values):
            addr = address + offset
            name = _register_name_for_address(addr)
            clamped = False
            value = raw_value
            if name is not None:
                lo, hi = WRITE_BOUNDS[name]
                _reg_addr, scale = WRITE_REGISTERS[name]
                lo_raw, hi_raw = int(lo * scale), int(hi * scale)
                if value < lo_raw:
                    value, clamped = lo_raw, True
                elif value > hi_raw:
                    value, clamped = hi_raw, True
            clamped_values.append(value)
            self.log.append(
                WriteLogEntry(
                    address=addr, raw_value=raw_value, accepted=True,
                    clamped=clamped, source=self.source,
                )
            )
        super().setValues(address, clamped_values)


def build_datastore(
    source: str = "manual",
) -> tuple[
    ModbusServerContext,
    ArbitratedWriteBlock,
    ModbusSequentialDataBlock,
]:
    """Build the combined holding-register datastore for the Modbus server.

    Args:
        source: Write authority tag passed through to the ArbitratedWriteBlock.

    Returns:
        Tuple of (ModbusServerContext, ArbitratedWriteBlock, read data block)
        so callers can also inspect writes/reads directly.
    """
    read_block = ModbusSequentialDataBlock(0, [0] * READ_BLOCK_SIZE)
    write_block = ArbitratedWriteBlock(source=source)

    class _CombinedBlock:
        """Routes get/set to the read block below address 100, write
        block at/above it — lets one holding-register space serve both
        without pymodbus's block-per-function-code split.

        The read block remains writable because the external orchestrator
        publishes plant outputs through ordinary holding-register writes.
        There is no client authentication in this local prototype, so the
        protocol does not prevent another client from spoofing a reading.
        """

        def getValues(self, address, count=1):
            """Route a read to the write block or read block by address.

            Args:
                address: Zero-based Modbus register address to read from.
                count: Number of consecutive registers to read.

            Returns:
                Raw register values from whichever block owns the address.
            """
            if address >= WRITE_BLOCK_BASE:
                return write_block.getValues(address, count)
            return read_block.getValues(address, count)

        def setValues(self, address, values):
            """Route a write to the write block or read block by address.

            Args:
                address: Zero-based Modbus register address to start writing at.
                values: Register values to write, starting at address.
            """
            if address >= WRITE_BLOCK_BASE:
                write_block.setValues(address, values)
            else:
                read_block.setValues(address, values)

        def validate(self, address, count=1):
            """Route an address-range validity check by address.

            Args:
                address: Zero-based Modbus register address to check.
                count: Number of consecutive registers to validate.

            Returns:
                True if the range is valid within whichever block owns it.
            """
            if address >= WRITE_BLOCK_BASE:
                return write_block.validate(address, count)
            return read_block.validate(address, count)

    combined = _CombinedBlock()
    slave_ctx = ModbusSlaveContext(hr=combined, zero_mode=True)
    return ModbusServerContext(slaves=slave_ctx, single=True), write_block, read_block
