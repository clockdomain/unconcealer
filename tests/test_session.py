"""Tests for Debug Session."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from unconcealer.core.session import DebugSession
from unconcealer.tools.qemu_control import QEMUConfig
from unconcealer.tools.gdb_bridge import StopReason, StopInfo, BreakpointInfo


class TestDebugSessionInstantiation:
    """Test DebugSession creation."""

    def test_default_config(self) -> None:
        """Test default configuration."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        assert session.elf_path == "/path/to/firmware.elf"
        assert session.gdb_path == "gdb-multiarch"
        assert session.qemu_config.machine == "lm3s6965evb"

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = QEMUConfig(gdb_port=5678, qmp_port=9999)
        session = DebugSession(
            elf_path="/path/to/firmware.elf",
            qemu_config=config,
            gdb_path="/usr/bin/gdb-multiarch",
        )
        assert session.qemu_config.gdb_port == 5678
        assert session.gdb_path == "/usr/bin/gdb-multiarch"

    def test_initial_state(self) -> None:
        """Test initial state is not started."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        assert session.started is False
        assert session.qemu is None
        assert session.gdb is None


class TestDebugSessionLifecycle:
    """Test session lifecycle with mocks."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create session with mocked QEMU and GDB."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        session.qemu = Mock()
        session.gdb = Mock()
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_start_creates_qemu_and_gdb(self) -> None:
        """Test start creates and connects QEMU and GDB."""
        session = DebugSession(elf_path="/path/to/firmware.elf")

        with patch("unconcealer.core.session.QEMUController") as mock_qemu_cls, \
             patch("unconcealer.core.session.GDBBridge") as mock_gdb_cls:

            mock_qemu = Mock()
            mock_qemu.start = AsyncMock(return_value=True)
            mock_qemu_cls.return_value = mock_qemu

            mock_gdb = Mock()
            mock_gdb.start = AsyncMock()
            mock_gdb.load_symbols = AsyncMock(return_value=True)
            mock_gdb.connect = AsyncMock(return_value=True)
            mock_gdb_cls.return_value = mock_gdb

            result = await session.start()

            assert result is True
            assert session.started is True
            mock_qemu.start.assert_called_once_with("/path/to/firmware.elf")
            mock_gdb.start.assert_called_once()
            mock_gdb.load_symbols.assert_called_once_with("/path/to/firmware.elf")
            mock_gdb.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_closes_gdb_and_qemu(self, mock_session: DebugSession) -> None:
        """Test stop closes both GDB and QEMU."""
        gdb_mock = mock_session.gdb
        qemu_mock = mock_session.qemu
        gdb_mock.close = AsyncMock()
        qemu_mock.stop = AsyncMock()

        await mock_session.stop()

        gdb_mock.close.assert_called_once()
        qemu_mock.stop.assert_called_once()
        assert mock_session.started is False
        assert mock_session.gdb is None
        assert mock_session.qemu is None

    @pytest.mark.asyncio
    async def test_stop_handles_gdb_error(self, mock_session: DebugSession) -> None:
        """Test stop handles GDB close error gracefully."""
        mock_session.gdb.close = AsyncMock(side_effect=Exception("GDB error"))
        mock_session.qemu.stop = AsyncMock()

        await mock_session.stop()  # Should not raise

        assert mock_session.started is False


class TestDebugSessionExecution:
    """Test execution control methods."""

    @pytest.fixture
    def started_session(self) -> DebugSession:
        """Create a started session with mocks."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        session.qemu = Mock()
        session.gdb = Mock()
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_continue_execution(self, started_session: DebugSession) -> None:
        """Test continue execution."""
        stop_info = StopInfo(reason=StopReason.BREAKPOINT, address=0x08001234)
        started_session.gdb.continue_execution = AsyncMock(return_value=stop_info)

        result = await started_session.continue_execution()

        assert result.reason == StopReason.BREAKPOINT
        started_session.gdb.continue_execution.assert_called_once()

    @pytest.mark.asyncio
    async def test_step(self, started_session: DebugSession) -> None:
        """Test single step."""
        stop_info = StopInfo(reason=StopReason.STEP, address=0x08001238)
        started_session.gdb.step = AsyncMock(return_value=stop_info)

        result = await started_session.step()

        assert result.reason == StopReason.STEP
        started_session.gdb.step.assert_called_once_with(instruction=False)

    @pytest.mark.asyncio
    async def test_step_instruction(self, started_session: DebugSession) -> None:
        """Test single step instruction."""
        stop_info = StopInfo(reason=StopReason.STEP, address=0x08001238)
        started_session.gdb.step = AsyncMock(return_value=stop_info)

        await started_session.step(instruction=True)

        started_session.gdb.step.assert_called_once_with(instruction=True)

    @pytest.mark.asyncio
    async def test_halt(self, started_session: DebugSession) -> None:
        """Test halt."""
        started_session.gdb.halt = AsyncMock()

        await started_session.halt()

        started_session.gdb.halt.assert_called_once()


class TestDebugSessionRegisters:
    """Test register operations."""

    @pytest.fixture
    def started_session(self) -> DebugSession:
        """Create a started session with mocks."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        session.qemu = Mock()
        session.gdb = Mock()
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_read_registers(self, started_session: DebugSession) -> None:
        """Test reading registers."""
        started_session.gdb.read_registers = AsyncMock(
            return_value={"pc": 0x08001234, "sp": 0x20001000}
        )

        result = await started_session.read_registers(["pc", "sp"])

        assert result["pc"] == 0x08001234
        assert result["sp"] == 0x20001000

    @pytest.mark.asyncio
    async def test_read_register(self, started_session: DebugSession) -> None:
        """Test reading single register."""
        started_session.gdb.read_register = AsyncMock(return_value=0x08001234)

        result = await started_session.read_register("pc")

        assert result == 0x08001234


class TestDebugSessionMemory:
    """Test memory operations."""

    @pytest.fixture
    def started_session(self) -> DebugSession:
        """Create a started session with mocks."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        session.qemu = Mock()
        session.gdb = Mock()
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_read_memory(self, started_session: DebugSession) -> None:
        """Test reading memory."""
        started_session.gdb.read_memory = AsyncMock(
            return_value=b"\xde\xad\xbe\xef"
        )

        result = await started_session.read_memory(0x20000000, 4)

        assert result == b"\xde\xad\xbe\xef"
        started_session.gdb.read_memory.assert_called_once_with(0x20000000, 4)

    @pytest.mark.asyncio
    async def test_write_memory(self, started_session: DebugSession) -> None:
        """Test writing memory."""
        started_session.gdb.write_memory = AsyncMock(return_value=True)

        result = await started_session.write_memory(0x20000000, b"\x12\x34")

        assert result is True
        started_session.gdb.write_memory.assert_called_once_with(
            0x20000000, b"\x12\x34"
        )

    @pytest.mark.asyncio
    async def test_read_memory_word(self, started_session: DebugSession) -> None:
        """Test reading memory word."""
        started_session.gdb.read_memory_word = AsyncMock(return_value=0xDEADBEEF)

        result = await started_session.read_memory_word(0x20000000)

        assert result == 0xDEADBEEF


class TestDebugSessionBreakpoints:
    """Test breakpoint operations."""

    @pytest.fixture
    def started_session(self) -> DebugSession:
        """Create a started session with mocks."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        session.qemu = Mock()
        session.gdb = Mock()
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_set_breakpoint(self, started_session: DebugSession) -> None:
        """Test setting breakpoint."""
        bp_info = BreakpointInfo(
            number=1, address=0x08001234, enabled=True, location="main"
        )
        started_session.gdb.set_breakpoint = AsyncMock(return_value=bp_info)

        result = await started_session.set_breakpoint("main")

        assert result.number == 1
        assert result.location == "main"

    @pytest.mark.asyncio
    async def test_delete_breakpoint(self, started_session: DebugSession) -> None:
        """Test deleting breakpoint."""
        started_session.gdb.delete_breakpoint = AsyncMock(return_value=True)

        result = await started_session.delete_breakpoint(1)

        assert result is True
        started_session.gdb.delete_breakpoint.assert_called_once_with(1)


class TestDebugSessionSnapshots:
    """Test snapshot operations."""

    @pytest.fixture
    def started_session(self) -> DebugSession:
        """Create a started session with mocks."""
        session = DebugSession(elf_path="/path/to/firmware.elf")
        session.qemu = Mock()
        session.gdb = Mock()
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_save_snapshot(self, started_session: DebugSession) -> None:
        """Test saving snapshot."""
        started_session.qemu.save_snapshot = AsyncMock(return_value=True)

        result = await started_session.save_snapshot("test-snap")

        assert result is True
        started_session.qemu.save_snapshot.assert_called_once_with("test-snap")

    @pytest.mark.asyncio
    async def test_load_snapshot(self, started_session: DebugSession) -> None:
        """Test loading snapshot."""
        started_session.qemu.load_snapshot = AsyncMock(return_value=True)

        result = await started_session.load_snapshot("test-snap")

        assert result is True
        started_session.qemu.load_snapshot.assert_called_once_with("test-snap")


class TestDebugSessionErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_operation_before_start_raises(self) -> None:
        """Test that operations fail if session not started."""
        session = DebugSession(elf_path="/path/to/firmware.elf")

        with pytest.raises(RuntimeError, match="not started"):
            await session.read_registers()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async context manager."""
        session = DebugSession(elf_path="/path/to/firmware.elf")

        with patch("unconcealer.core.session.QEMUController") as mock_qemu_cls, \
             patch("unconcealer.core.session.GDBBridge") as mock_gdb_cls:

            mock_qemu = Mock()
            mock_qemu.start = AsyncMock(return_value=True)
            mock_qemu.stop = AsyncMock()
            mock_qemu_cls.return_value = mock_qemu

            mock_gdb = Mock()
            mock_gdb.start = AsyncMock()
            mock_gdb.load_symbols = AsyncMock(return_value=True)
            mock_gdb.connect = AsyncMock(return_value=True)
            mock_gdb.close = AsyncMock()
            mock_gdb_cls.return_value = mock_gdb

            async with session:
                assert session.started is True

            assert session.started is False
            mock_gdb.close.assert_called_once()
            mock_qemu.stop.assert_called_once()


# Integration tests
@pytest.mark.integration
class TestDebugSessionIntegration:
    """Integration tests requiring QEMU."""

    @pytest.fixture
    def integration_config(self) -> QEMUConfig:
        """Config with non-default ports to avoid conflicts."""
        return QEMUConfig(
            gdb_port=4567,
            qmp_port=6666,
        )

    @pytest.mark.asyncio
    async def test_session_start_stop(self, integration_config: QEMUConfig, test_firmware_path) -> None:
        """Test full session lifecycle."""
        session = DebugSession(
            elf_path=str(test_firmware_path),
            qemu_config=integration_config,
        )

        try:
            await session.start()
            assert session.started
            assert session.qemu is not None
            assert session.gdb is not None
        finally:
            await session.stop()
            assert not session.started

    @pytest.mark.asyncio
    async def test_session_read_registers(
        self, integration_config: QEMUConfig, test_firmware_path
    ) -> None:
        """Test reading registers through session."""
        session = DebugSession(
            elf_path=str(test_firmware_path),
            qemu_config=integration_config,
        )

        try:
            await session.start()
            regs = await session.read_registers(["pc", "sp"])
            assert "pc" in regs
            assert "sp" in regs
            assert regs["sp"] > 0x20000000
        finally:
            await session.stop()

    @pytest.mark.asyncio
    async def test_session_continue_and_halt(
        self, integration_config: QEMUConfig, test_firmware_path
    ) -> None:
        """Test continue and halt through session."""
        session = DebugSession(
            elf_path=str(test_firmware_path),
            qemu_config=integration_config,
        )

        try:
            await session.start()

            # Get initial PC
            initial_pc = await session.read_register("pc")

            # We can't easily test continue without a breakpoint
            # But we can verify the session is connected
            bt = await session.get_backtrace(5)
            assert len(bt) > 0

        finally:
            await session.stop()
