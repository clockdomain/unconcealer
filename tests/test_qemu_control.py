"""Tests for QEMU Controller."""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from unconcealer.tools.qemu_control import (
    QEMUController,
    QEMUConfig,
)


class TestQEMUConfig:
    """Test QEMUConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = QEMUConfig()
        assert config.qemu_path == "qemu-system-arm"
        assert config.machine == "lm3s6965evb"
        assert config.cpu == "cortex-m3"
        assert config.memory == "64K"
        assert config.gdb_port == 1234
        assert config.qmp_port == 4444
        assert config.extra_args == []

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = QEMUConfig(
            qemu_path="/usr/bin/qemu-system-arm",
            machine="mps2-an385",
            cpu="cortex-m4",
            memory="1M",
            gdb_port=2345,
            qmp_port=5555,
            extra_args=["-d", "in_asm"],
        )
        assert config.qemu_path == "/usr/bin/qemu-system-arm"
        assert config.machine == "mps2-an385"
        assert config.cpu == "cortex-m4"
        assert config.gdb_port == 2345
        assert config.qmp_port == 5555
        assert config.extra_args == ["-d", "in_asm"]


class TestQEMUControllerInstantiation:
    """Test QEMU controller creation."""

    def test_default_config(self) -> None:
        """Test default configuration is applied."""
        qemu = QEMUController()
        assert qemu.config.machine == "lm3s6965evb"
        assert qemu.config.gdb_port == 1234

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = QEMUConfig(gdb_port=9999)
        qemu = QEMUController(config)
        assert qemu.config.gdb_port == 9999

    def test_initial_state(self) -> None:
        """Test initial state is not running."""
        qemu = QEMUController()
        assert qemu.process is None
        assert qemu.qmp_socket is None
        assert qemu.running is False


class TestQEMUControllerProperties:
    """Test QEMU controller properties."""

    def test_running_property(self) -> None:
        """Test running property."""
        qemu = QEMUController()
        assert qemu.running is False
        qemu._running = True
        assert qemu.running is True

    def test_gdb_port_property(self) -> None:
        """Test gdb_port property."""
        config = QEMUConfig(gdb_port=5678)
        qemu = QEMUController(config)
        assert qemu.gdb_port == 5678

    def test_elf_path_property(self) -> None:
        """Test elf_path property."""
        qemu = QEMUController()
        assert qemu.elf_path is None
        qemu._elf_path = "/path/to/firmware.elf"
        assert qemu.elf_path == "/path/to/firmware.elf"


class TestQEMUControllerWithMock:
    """Test QEMU controller with mocked subprocess and socket."""

    @pytest.fixture
    def mock_qemu(self) -> QEMUController:
        """Create QEMU controller with mocked internals."""
        qemu = QEMUController()
        qemu.qmp_socket = Mock()
        qemu._running = True
        return qemu

    @pytest.mark.asyncio
    async def test_qmp_send(self, mock_qemu: QEMUController) -> None:
        """Test QMP message sending."""
        await mock_qemu._qmp_send({"execute": "test"})
        mock_qemu.qmp_socket.send.assert_called_once()
        sent_data = mock_qemu.qmp_socket.send.call_args[0][0]
        assert b'"execute": "test"' in sent_data
        assert sent_data.endswith(b"\n")

    @pytest.mark.asyncio
    async def test_qmp_execute(self, mock_qemu: QEMUController) -> None:
        """Test QMP command execution."""
        # Mock recv to return success response
        mock_qemu._qmp_recv = AsyncMock(return_value={"return": {}})
        mock_qemu._qmp_send = AsyncMock()

        result = await mock_qemu.qmp_execute("stop")

        mock_qemu._qmp_send.assert_called_once_with({"execute": "stop"})
        assert "return" in result

    @pytest.mark.asyncio
    async def test_qmp_execute_with_args(self, mock_qemu: QEMUController) -> None:
        """Test QMP command with arguments."""
        mock_qemu._qmp_recv = AsyncMock(return_value={"return": {}})
        mock_qemu._qmp_send = AsyncMock()

        await mock_qemu.qmp_execute("human-monitor-command",
                                     {"command-line": "info registers"})

        expected = {
            "execute": "human-monitor-command",
            "arguments": {"command-line": "info registers"}
        }
        mock_qemu._qmp_send.assert_called_once_with(expected)

    @pytest.mark.asyncio
    async def test_pause(self, mock_qemu: QEMUController) -> None:
        """Test pause command."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"return": {}})
        result = await mock_qemu.pause()
        assert result is True
        mock_qemu.qmp_execute.assert_called_once_with("stop")

    @pytest.mark.asyncio
    async def test_resume(self, mock_qemu: QEMUController) -> None:
        """Test resume command."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"return": {}})
        result = await mock_qemu.resume()
        assert result is True
        mock_qemu.qmp_execute.assert_called_once_with("cont")

    @pytest.mark.asyncio
    async def test_reset(self, mock_qemu: QEMUController) -> None:
        """Test reset command."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"return": {}})
        result = await mock_qemu.reset()
        assert result is True
        mock_qemu.qmp_execute.assert_called_once_with("system_reset")

    @pytest.mark.asyncio
    async def test_save_snapshot(self, mock_qemu: QEMUController) -> None:
        """Test save snapshot."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"return": ""})
        result = await mock_qemu.save_snapshot("test-snap")
        assert result is True
        mock_qemu.qmp_execute.assert_called_once_with(
            "human-monitor-command",
            {"command-line": "savevm test-snap"}
        )

    @pytest.mark.asyncio
    async def test_save_snapshot_error(self, mock_qemu: QEMUController) -> None:
        """Test save snapshot with error."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"error": "no snapshot support"})
        result = await mock_qemu.save_snapshot("test-snap")
        assert result is False

    @pytest.mark.asyncio
    async def test_load_snapshot(self, mock_qemu: QEMUController) -> None:
        """Test load snapshot."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"return": ""})
        result = await mock_qemu.load_snapshot("test-snap")
        assert result is True
        mock_qemu.qmp_execute.assert_called_once_with(
            "human-monitor-command",
            {"command-line": "loadvm test-snap"}
        )

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, mock_qemu: QEMUController) -> None:
        """Test delete snapshot."""
        mock_qemu.qmp_execute = AsyncMock(return_value={"return": ""})
        result = await mock_qemu.delete_snapshot("test-snap")
        assert result is True
        mock_qemu.qmp_execute.assert_called_once_with(
            "human-monitor-command",
            {"command-line": "delvm test-snap"}
        )

    @pytest.mark.asyncio
    async def test_query_status(self, mock_qemu: QEMUController) -> None:
        """Test query status."""
        mock_qemu.qmp_execute = AsyncMock(return_value={
            "return": {"running": True, "status": "running"}
        })
        status = await mock_qemu.query_status()
        assert status["running"] is True
        assert status["status"] == "running"

    @pytest.mark.asyncio
    async def test_query_cpus(self, mock_qemu: QEMUController) -> None:
        """Test query CPUs."""
        mock_qemu.qmp_execute = AsyncMock(return_value={
            "return": [{"cpu-index": 0, "thread-id": 1234}]
        })
        cpus = await mock_qemu.query_cpus()
        assert len(cpus) == 1
        assert cpus[0]["cpu-index"] == 0

    @pytest.mark.asyncio
    async def test_stop(self, mock_qemu: QEMUController) -> None:
        """Test stop shuts down cleanly."""
        mock_qemu.qmp_execute = AsyncMock()
        process_mock = Mock()
        process_mock.terminate = Mock()
        process_mock.wait = Mock()
        mock_qemu.process = process_mock

        await mock_qemu.stop()

        mock_qemu.qmp_execute.assert_called_with("quit")
        process_mock.terminate.assert_called_once()
        assert mock_qemu.running is False
        assert mock_qemu.qmp_socket is None
        assert mock_qemu.process is None


class TestQEMUControllerStart:
    """Test QEMU start functionality."""

    @pytest.mark.asyncio
    async def test_start_qemu_not_found(self) -> None:
        """Test error when QEMU executable not found."""
        config = QEMUConfig(qemu_path="/nonexistent/qemu")
        qemu = QEMUController(config)

        with pytest.raises(RuntimeError, match="QEMU not found"):
            await qemu.start("/path/to/firmware.elf")

    @pytest.mark.asyncio
    @patch("subprocess.Popen")
    async def test_start_builds_correct_command(self, mock_popen: Mock) -> None:
        """Test start builds correct QEMU command."""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_process.stderr = Mock()
        mock_process.stderr.read.return_value = b""
        mock_popen.return_value = mock_process

        config = QEMUConfig(
            machine="lm3s6965evb",
            cpu="cortex-m3",
            gdb_port=1234,
            qmp_port=4444,
        )
        qemu = QEMUController(config)

        # Mock QMP connection
        qemu._connect_qmp = AsyncMock()

        await qemu.start("/path/to/firmware.elf")

        # Verify command was built correctly
        call_args = mock_popen.call_args[0][0]
        assert "-machine" in call_args
        assert "lm3s6965evb" in call_args
        assert "-cpu" in call_args
        assert "cortex-m3" in call_args
        assert "-kernel" in call_args
        assert "/path/to/firmware.elf" in call_args
        assert "-gdb" in call_args
        assert "tcp::1234" in call_args
        assert "-S" in call_args  # Wait for GDB


# Integration tests - require actual QEMU running
@pytest.mark.integration
class TestQEMUControllerIntegration:
    """Integration tests requiring QEMU.

    These tests start their own QEMU instances on different ports
    to avoid conflicts with existing QEMU processes.
    """

    @pytest.fixture
    def integration_config(self) -> QEMUConfig:
        """Config with non-default ports to avoid conflicts."""
        return QEMUConfig(
            gdb_port=3456,  # Different from default 1234
            qmp_port=5555,  # Different from default 4444
        )

    @pytest.mark.asyncio
    async def test_qemu_start_stop(self, integration_config: QEMUConfig, test_firmware_path) -> None:
        """Test QEMU lifecycle."""
        qemu = QEMUController(integration_config)

        try:
            started = await qemu.start(str(test_firmware_path))
            assert started
            assert qemu.running
        finally:
            await qemu.stop()
            assert not qemu.running

    @pytest.mark.asyncio
    async def test_qemu_pause_resume(self, integration_config: QEMUConfig, test_firmware_path) -> None:
        """Test pause/resume functionality."""
        qemu = QEMUController(integration_config)

        try:
            await qemu.start(str(test_firmware_path))

            # Should start paused (due to -S flag)
            status = await qemu.query_status()
            assert status.get("status") == "paused" or not status.get("running")

            # Resume
            resumed = await qemu.resume()
            assert resumed

            # Pause
            paused = await qemu.pause()
            assert paused

        finally:
            await qemu.stop()

    @pytest.mark.asyncio
    async def test_qemu_query_cpus(self, integration_config: QEMUConfig, test_firmware_path) -> None:
        """Test CPU query."""
        qemu = QEMUController(integration_config)

        try:
            await qemu.start(str(test_firmware_path))

            cpus = await qemu.query_cpus()
            assert len(cpus) > 0
            assert "cpu-index" in cpus[0]

        finally:
            await qemu.stop()
