"""Tests for GDB Bridge."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from unconcealer.tools.gdb_bridge import (
    GDBBridge,
    StopReason,
    StopInfo,
    BreakpointInfo,
    EvalResult,
)
from unconcealer.tools.qemu_control import QEMUController, QEMUConfig


class TestGDBBridgeInstantiation:
    """Test GDB bridge creation."""

    def test_default_gdb_path(self) -> None:
        """Test default GDB path is arm-none-eabi-gdb."""
        gdb = GDBBridge()
        assert gdb.gdb_path == "arm-none-eabi-gdb"

    def test_custom_gdb_path(self) -> None:
        """Test custom GDB path."""
        gdb = GDBBridge(gdb_path="gdb-multiarch")
        assert gdb.gdb_path == "gdb-multiarch"

    def test_initial_state(self) -> None:
        """Test initial state is disconnected."""
        gdb = GDBBridge()
        assert gdb.gdb is None
        assert gdb.connected is False


class TestGDBBridgeParsing:
    """Test response parsing methods."""

    def test_parse_int_decimal(self) -> None:
        """Test parsing decimal integer."""
        gdb = GDBBridge()
        assert gdb._parse_int("42") == 42

    def test_parse_int_hex(self) -> None:
        """Test parsing hex integer."""
        gdb = GDBBridge()
        assert gdb._parse_int("0x1234") == 0x1234
        assert gdb._parse_int("0X1234") == 0x1234

    def test_parse_int_empty(self) -> None:
        """Test parsing empty string."""
        gdb = GDBBridge()
        assert gdb._parse_int("") == 0

    def test_check_success_done(self) -> None:
        """Test success detection for done message."""
        gdb = GDBBridge()
        response = [{"message": "done", "payload": {}}]
        assert gdb._check_success(response) is True

    def test_check_success_error(self) -> None:
        """Test failure detection for error message."""
        gdb = GDBBridge()
        response = [{"message": "error", "payload": {"msg": "failed"}}]
        assert gdb._check_success(response) is False

    def test_parse_stop_breakpoint(self) -> None:
        """Test parsing breakpoint stop."""
        gdb = GDBBridge()
        response = [{
            "message": "stopped",
            "payload": {
                "reason": "breakpoint-hit",
                "bkptno": "1",
                "frame": {"addr": "0x08001234", "func": "main"}
            }
        }]
        stop = gdb._parse_stop(response)
        assert stop.reason == StopReason.BREAKPOINT
        assert stop.address == 0x08001234

    def test_parse_stop_signal(self) -> None:
        """Test parsing signal stop."""
        gdb = GDBBridge()
        response = [{
            "message": "stopped",
            "payload": {
                "reason": "signal",
                "signal-name": "SIGTRAP",
                "frame": {"addr": "0x08001000"}
            }
        }]
        stop = gdb._parse_stop(response)
        assert stop.reason == StopReason.SIGNAL
        assert stop.signal_name == "SIGTRAP"

    def test_parse_memory_bytes(self) -> None:
        """Test parsing memory read response."""
        gdb = GDBBridge()
        response = [{
            "message": "done",
            "payload": {
                "memory": [{
                    "begin": "0x20000000",
                    "contents": "deadbeef"
                }]
            }
        }]
        data = gdb._parse_memory_bytes(response)
        assert data == bytes.fromhex("deadbeef")

    def test_parse_breakpoint(self) -> None:
        """Test parsing breakpoint creation response."""
        gdb = GDBBridge()
        response = [{
            "message": "done",
            "payload": {
                "bkpt": {
                    "number": "1",
                    "addr": "0x08001234",
                    "enabled": "y",
                    "original-location": "main"
                }
            }
        }]
        bp = gdb._parse_breakpoint(response)
        assert bp is not None
        assert bp.number == 1
        assert bp.address == 0x08001234
        assert bp.enabled is True
        assert bp.location == "main"


class TestGDBBridgeWithMock:
    """Test GDB bridge with mocked GdbController."""

    @pytest.fixture
    def mock_gdb(self) -> GDBBridge:
        """Create GDB bridge with mocked controller."""
        gdb = GDBBridge()
        gdb.gdb = Mock()
        return gdb

    @pytest.mark.asyncio
    async def test_load_symbols(self, mock_gdb: GDBBridge) -> None:
        """Test loading symbols."""
        mock_gdb.gdb.write.return_value = [{"message": "done"}]
        result = await mock_gdb.load_symbols("/path/to/firmware.elf")
        assert result is True
        mock_gdb.gdb.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_continue_execution(self, mock_gdb: GDBBridge) -> None:
        """Test continue execution."""
        mock_gdb.gdb.write.return_value = [{
            "message": "stopped",
            "payload": {
                "reason": "breakpoint-hit",
                "frame": {"addr": "0x08001234"}
            }
        }]
        stop = await mock_gdb.continue_execution()
        assert stop.reason == StopReason.BREAKPOINT
        mock_gdb.gdb.write.assert_called_with("-exec-continue", timeout_sec=10)

    @pytest.mark.asyncio
    async def test_read_memory(self, mock_gdb: GDBBridge) -> None:
        """Test memory read."""
        mock_gdb.gdb.write.return_value = [{
            "message": "done",
            "payload": {
                "memory": [{"contents": "12345678"}]
            }
        }]
        data = await mock_gdb.read_memory(0x20000000, 4)
        assert data == bytes.fromhex("12345678")

    @pytest.mark.asyncio
    async def test_write_memory(self, mock_gdb: GDBBridge) -> None:
        """Test memory write."""
        mock_gdb.gdb.write.return_value = [{"message": "done"}]
        result = await mock_gdb.write_memory(0x20000000, b"\xde\xad\xbe\xef")
        assert result is True
        mock_gdb.gdb.write.assert_called_with(
            "-data-write-memory-bytes 0x20000000 deadbeef", timeout_sec=10
        )

    @pytest.mark.asyncio
    async def test_set_breakpoint(self, mock_gdb: GDBBridge) -> None:
        """Test setting breakpoint."""
        mock_gdb.gdb.write.return_value = [{
            "message": "done",
            "payload": {
                "bkpt": {
                    "number": "1",
                    "addr": "0x08001234",
                    "enabled": "y",
                    "original-location": "main"
                }
            }
        }]
        bp = await mock_gdb.set_breakpoint("main")
        assert bp.number == 1
        assert bp.location == "main"

    @pytest.mark.asyncio
    async def test_evaluate(self, mock_gdb: GDBBridge) -> None:
        """Test expression evaluation."""
        mock_gdb.gdb.write.return_value = [{
            "message": "done",
            "payload": {"value": "42"}
        }]
        result = await mock_gdb.evaluate("2 + 2")
        assert result.value == "42"

    @pytest.mark.asyncio
    async def test_close(self, mock_gdb: GDBBridge) -> None:
        """Test closing connection."""
        gdb_mock = mock_gdb.gdb  # Save reference before close
        await mock_gdb.close()
        gdb_mock.exit.assert_called_once()
        assert mock_gdb.gdb is None
        assert mock_gdb.connected is False


# Integration tests - self-contained with own QEMU instance
@pytest.mark.integration
class TestGDBBridgeIntegration:
    """Integration tests that start their own QEMU instance."""

    @pytest.fixture
    async def qemu(self, test_firmware_path):
        """Start QEMU for the test."""
        config = QEMUConfig(gdb_port=2345, qmp_port=3456)
        qemu = QEMUController(config)
        await qemu.start(str(test_firmware_path))
        yield qemu
        await qemu.stop()

    @pytest.mark.asyncio
    async def test_connect_to_qemu(self, qemu: QEMUController, test_firmware_path) -> None:
        """Test connecting to QEMU gdbstub."""
        gdb = GDBBridge(gdb_path='gdb-multiarch')
        try:
            await gdb.start()
            await gdb.load_symbols(str(test_firmware_path))
            connected = await gdb.connect('localhost', qemu.gdb_port)
            assert connected, "Failed to connect to QEMU"
            assert gdb.connected
        finally:
            await gdb.close()

    @pytest.mark.asyncio
    async def test_read_registers(self, qemu: QEMUController, test_firmware_path) -> None:
        """Test reading registers from QEMU."""
        gdb = GDBBridge(gdb_path='gdb-multiarch')
        try:
            await gdb.start()
            await gdb.load_symbols(str(test_firmware_path))
            await gdb.connect('localhost', qemu.gdb_port)

            regs = await gdb.read_registers(['pc', 'sp', 'lr'])
            assert 'pc' in regs
            assert 'sp' in regs
            assert regs['sp'] > 0x20000000  # RAM region
        finally:
            await gdb.close()

    @pytest.mark.asyncio
    async def test_read_memory(self, qemu: QEMUController, test_firmware_path) -> None:
        """Test reading memory from QEMU."""
        gdb = GDBBridge(gdb_path='gdb-multiarch')
        try:
            await gdb.start()
            await gdb.load_symbols(str(test_firmware_path))
            await gdb.connect('localhost', qemu.gdb_port)

            # Read vector table (should have valid stack pointer and reset vector)
            mem = await gdb.read_memory(0x00000000, 8)
            assert len(mem) == 8
            # First word is initial SP, should be in RAM
            sp = int.from_bytes(mem[0:4], 'little')
            assert sp >= 0x20000000
        finally:
            await gdb.close()

    @pytest.mark.asyncio
    async def test_backtrace(self, qemu: QEMUController, test_firmware_path) -> None:
        """Test getting backtrace from QEMU."""
        gdb = GDBBridge(gdb_path='gdb-multiarch')
        try:
            await gdb.start()
            await gdb.load_symbols(str(test_firmware_path))
            await gdb.connect('localhost', qemu.gdb_port)

            bt = await gdb.get_backtrace(10)
            assert len(bt) > 0
            assert 'func' in bt[0]
            assert 'addr' in bt[0]
        finally:
            await gdb.close()
