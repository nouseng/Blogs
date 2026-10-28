"""Entry point for the standalone Modbus TCP gateway server."""

from pymodbus.server import StartTcpServer
from gateway.registers import build_datastore


def make_context(source: str = "manual"):
    """Build the server context (thin wrapper around build_datastore).

    Args:
        source: Write authority tag passed through to build_datastore.

    Returns:
        Tuple of (ModbusServerContext, ArbitratedWriteBlock, read data block).
    """
    context, write_block, read_block = build_datastore(source=source)
    return context, write_block, read_block


def run_server(host: str = "0.0.0.0", port: int = 5020) -> None:
    """Start the blocking Modbus TCP server.

    Args:
        host: Bind address.
        port: TCP port to listen on.
    """
    context, _write_block, _read_block = make_context()
    StartTcpServer(context=context, address=(host, port))


if __name__ == "__main__":
    run_server()
