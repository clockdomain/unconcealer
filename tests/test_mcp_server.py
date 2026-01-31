"""Tests for MCP server module."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from unconcealer.mcp.session_manager import SessionManager, SessionInfo
from unconcealer.mcp.stdio_server import StdioMcpServer, _text_response


class TestSessionManager:
    """Test SessionManager class."""

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        manager = SessionManager()
        assert manager.gdb_path == "gdb-multiarch"
        assert "arm" in manager.qemu_paths
        assert "riscv32" in manager.qemu_paths
        assert "riscv64" in manager.qemu_paths

    def test_init_custom_paths(self) -> None:
        """Test custom path initialization."""
        manager = SessionManager(
            gdb_path="/custom/gdb",
            qemu_arm_path="/custom/qemu-arm",
            qemu_riscv32_path="/custom/qemu-rv32",
        )
        assert manager.gdb_path == "/custom/gdb"
        assert manager.qemu_paths["arm"] == "/custom/qemu-arm"
        assert manager.qemu_paths["riscv32"] == "/custom/qemu-rv32"

    def test_get_qemu_path_arm(self) -> None:
        """Test QEMU path selection for ARM."""
        manager = SessionManager()
        path = manager._get_qemu_path("lm3s6965evb", "cortex-m3")
        assert path == "qemu-system-arm"

    def test_get_qemu_path_riscv32(self) -> None:
        """Test QEMU path selection for RISC-V 32."""
        manager = SessionManager()
        path = manager._get_qemu_path("sifive_e", "rv32")
        assert path == "qemu-system-riscv32"

    def test_get_qemu_path_riscv64(self) -> None:
        """Test QEMU path selection for RISC-V 64."""
        manager = SessionManager()
        path = manager._get_qemu_path("virt", "rv64")
        assert path == "qemu-system-riscv64"

    def test_allocate_port(self) -> None:
        """Test port allocation."""
        manager = SessionManager()
        port1 = manager._allocate_port()
        port2 = manager._allocate_port()
        assert port2 == port1 + 1

    def test_list_sessions_empty(self) -> None:
        """Test listing sessions when none exist."""
        manager = SessionManager()
        sessions = manager.list_sessions()
        assert sessions == []

    def test_get_current_session_none(self) -> None:
        """Test getting current session when none exist."""
        manager = SessionManager()
        assert manager.get_current_session() is None

    def test_get_current_name_none(self) -> None:
        """Test getting current name when none exist."""
        manager = SessionManager()
        assert manager.get_current_name() is None

    def test_set_current_invalid(self) -> None:
        """Test setting current to invalid session."""
        manager = SessionManager()
        result = manager.set_current("nonexistent")
        assert result is False

    def test_to_dict_empty(self) -> None:
        """Test serialization with no sessions."""
        manager = SessionManager()
        data = manager.to_dict()
        assert data["current"] is None
        assert data["sessions"] == []

    @pytest.mark.asyncio
    async def test_start_session_file_not_found(self) -> None:
        """Test starting session with missing ELF."""
        manager = SessionManager()
        with pytest.raises(FileNotFoundError):
            await manager.start_session("/nonexistent/file.elf")

    @pytest.mark.asyncio
    async def test_start_session_with_mock(self, tmp_path: Path) -> None:
        """Test starting a session with mocked DebugSession."""
        # Create a dummy ELF file
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()

        # Mock DebugSession
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            info = await manager.start_session(str(elf_file))

        assert info.name == "test"
        assert info.elf_path == str(elf_file)
        assert info.is_active is True
        assert manager.get_current_name() == "test"

    @pytest.mark.asyncio
    async def test_stop_session_not_found(self) -> None:
        """Test stopping nonexistent session."""
        manager = SessionManager()
        result = await manager.stop_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_session_lifecycle_with_mock(self, tmp_path: Path) -> None:
        """Test full session lifecycle with mocked components."""
        elf_file = tmp_path / "firmware.elf"
        elf_file.touch()

        manager = SessionManager()
        mock_session = AsyncMock()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            # Start session
            info = await manager.start_session(
                str(elf_file), name="test_session"
            )
            assert info.name == "test_session"
            assert len(manager.list_sessions()) == 1

            # Stop session
            result = await manager.stop_session("test_session")
            assert result is True
            assert len(manager.list_sessions()) == 0
            assert manager.get_current_session() is None

    @pytest.mark.asyncio
    async def test_multiple_sessions_with_mock(self, tmp_path: Path) -> None:
        """Test managing multiple sessions."""
        elf1 = tmp_path / "fw1.elf"
        elf2 = tmp_path / "fw2.elf"
        elf1.touch()
        elf2.touch()

        manager = SessionManager()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            await manager.start_session(str(elf1), name="session1")
            await manager.start_session(str(elf2), name="session2")

            assert len(manager.list_sessions()) == 2
            assert manager.get_current_name() == "session1"

            # Switch current
            manager.set_current("session2")
            assert manager.get_current_name() == "session2"

            # Stop first session
            await manager.stop_session("session1")
            assert len(manager.list_sessions()) == 1
            assert manager.get_current_name() == "session2"

    @pytest.mark.asyncio
    async def test_stop_all_sessions(self, tmp_path: Path) -> None:
        """Test stopping all sessions."""
        elf1 = tmp_path / "fw1.elf"
        elf2 = tmp_path / "fw2.elf"
        elf1.touch()
        elf2.touch()

        manager = SessionManager()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            await manager.start_session(str(elf1), name="s1")
            await manager.start_session(str(elf2), name="s2")
            assert len(manager.list_sessions()) == 2

            await manager.stop_all()
            assert len(manager.list_sessions()) == 0


class TestTextResponse:
    """Test _text_response helper."""

    def test_normal_response(self) -> None:
        """Test normal text response."""
        result = _text_response("Hello")
        assert result["content"][0]["text"] == "Hello"
        assert "is_error" not in result

    def test_error_response(self) -> None:
        """Test error response."""
        result = _text_response("Error!", is_error=True)
        assert result["content"][0]["text"] == "Error!"
        assert result["is_error"] is True


class TestStdioMcpServer:
    """Test StdioMcpServer class."""

    def test_init(self) -> None:
        """Test server initialization."""
        manager = SessionManager()
        server = StdioMcpServer(manager)
        assert server.server_name == "unconcealer"
        assert server.session_manager is manager

    def test_tool_definitions(self) -> None:
        """Test tool definitions are complete."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        tool_names = [t["name"] for t in server._tools]

        # Session management
        assert "start_session" in tool_names
        assert "stop_session" in tool_names
        assert "list_sessions" in tool_names

        # Debug tools
        assert "read_registers" in tool_names
        assert "read_memory" in tool_names
        assert "write_memory" in tool_names
        assert "continue_execution" in tool_names
        assert "step" in tool_names
        assert "halt" in tool_names
        assert "reset" in tool_names
        assert "set_breakpoint" in tool_names
        assert "delete_breakpoint" in tool_names
        assert "backtrace" in tool_names
        assert "evaluate" in tool_names
        assert "save_snapshot" in tool_names
        assert "load_snapshot" in tool_names

    def test_tool_definitions_have_schemas(self) -> None:
        """Test all tools have input schemas."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        for tool in server._tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    @pytest.mark.asyncio
    async def test_handle_initialize(self) -> None:
        """Test initialize request handling."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }

        response = await server._handle_request(request)

        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["serverInfo"]["name"] == "unconcealer"

    @pytest.mark.asyncio
    async def test_handle_tools_list(self) -> None:
        """Test tools/list request handling."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }

        response = await server._handle_request(request)

        assert response["id"] == 2
        assert "result" in response
        assert "tools" in response["result"]
        assert len(response["result"]["tools"]) > 10

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self) -> None:
        """Test unknown method handling."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "unknown/method",
            "params": {},
        }

        response = await server._handle_request(request)

        assert response["id"] == 3
        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_list_sessions_empty(self) -> None:
        """Test list_sessions with no sessions."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "list_sessions", "arguments": {}},
        }

        response = await server._handle_request(request)

        assert response["id"] == 4
        assert "result" in response
        assert "No active sessions" in response["result"]["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_handle_tool_no_session(self) -> None:
        """Test tool call without active session."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "read_registers", "arguments": {}},
        }

        response = await server._handle_request(request)

        assert response["id"] == 5
        assert "result" in response
        assert response["result"]["is_error"] is True
        assert "No active session" in response["result"]["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_handle_start_session_file_not_found(self) -> None:
        """Test start_session with missing file."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "start_session",
                "arguments": {"elf_path": "/nonexistent.elf"},
            },
        }

        response = await server._handle_request(request)

        assert response["id"] == 6
        assert "result" in response
        assert response["result"]["is_error"] is True
        assert "not found" in response["result"]["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_handle_start_session_success(self, tmp_path: Path) -> None:
        """Test successful start_session."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()
        server = StdioMcpServer(manager)

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            request = {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "start_session",
                    "arguments": {"elf_path": str(elf_file)},
                },
            }

            response = await server._handle_request(request)

            assert response["id"] == 7
            assert "result" in response
            assert "is_error" not in response["result"]
            assert "Started session" in response["result"]["content"][0]["text"]


class TestSessionInfo:
    """Test SessionInfo dataclass."""

    def test_create_session_info(self) -> None:
        """Test creating SessionInfo."""
        info = SessionInfo(
            name="test",
            elf_path="/path/to/firmware.elf",
            machine="lm3s6965evb",
            cpu="cortex-m3",
            gdb_port=1234,
        )
        assert info.name == "test"
        assert info.elf_path == "/path/to/firmware.elf"
        assert info.is_active is False
        assert info.session is None

    def test_session_info_with_session(self) -> None:
        """Test SessionInfo with session object."""
        mock_session = Mock()
        info = SessionInfo(
            name="test",
            elf_path="/path.elf",
            machine="mps2-an385",
            cpu="cortex-m3",
            gdb_port=1234,
            session=mock_session,
            is_active=True,
        )
        assert info.session is mock_session
        assert info.is_active is True


class TestSessionManagerArchitecture:
    """Test SessionManager architecture features."""

    @pytest.mark.asyncio
    async def test_session_detects_architecture(self, tmp_path: Path) -> None:
        """Test that sessions detect architecture from cpu/machine."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            info = await manager.start_session(
                str(elf_file), cpu="cortex-m4", machine="netduinoplus2"
            )
            assert info.architecture == "cortex-m4"

    @pytest.mark.asyncio
    async def test_session_detects_riscv_architecture(self, tmp_path: Path) -> None:
        """Test RISC-V architecture detection."""
        elf_file = tmp_path / "riscv.elf"
        elf_file.touch()

        manager = SessionManager()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            info = await manager.start_session(
                str(elf_file), cpu="rv32", machine="sifive_e"
            )
            assert info.architecture == "riscv32"

    @pytest.mark.asyncio
    async def test_get_architecture_no_session(self) -> None:
        """Test get_architecture with no active session."""
        manager = SessionManager()
        arch = manager.get_architecture()
        assert arch is None

    @pytest.mark.asyncio
    async def test_get_architecture_with_session(self, tmp_path: Path) -> None:
        """Test get_architecture with active session."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            await manager.start_session(str(elf_file), cpu="cortex-m3")
            arch = manager.get_architecture()
            assert arch is not None
            # cortex-m3 maps to CortexMTarget which has name "cortex-m"
            assert "cortex" in arch.name.lower()

    @pytest.mark.asyncio
    async def test_get_current_architecture(self, tmp_path: Path) -> None:
        """Test get_current_architecture."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=AsyncMock(),
        ):
            await manager.start_session(str(elf_file), cpu="cortex-m0")
            arch = manager.get_current_architecture()
            assert arch is not None
            assert "cortex" in arch.name.lower() or "m0" in arch.name.lower()


class TestArchitectureMcpTools:
    """Test architecture-specific MCP tools."""

    def test_architecture_tools_exist(self) -> None:
        """Test that architecture tools are defined."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        tool_names = [t["name"] for t in server._tools]

        assert "read_fault_registers" in tool_names
        assert "read_exception_frame" in tool_names
        assert "check_interrupt_priorities" in tool_names
        assert "show_memory_protection" in tool_names
        assert "analyze_crash" in tool_names

    def test_architecture_tools_have_schemas(self) -> None:
        """Test architecture tools have proper schemas."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        arch_tools = [
            "read_fault_registers",
            "read_exception_frame",
            "check_interrupt_priorities",
            "show_memory_protection",
            "analyze_crash",
        ]

        for tool in server._tools:
            if tool["name"] in arch_tools:
                assert "description" in tool
                assert "inputSchema" in tool
                # All should have optional session parameter
                props = tool["inputSchema"].get("properties", {})
                assert "session" in props or len(props) == 0

    @pytest.mark.asyncio
    async def test_read_fault_registers_no_session(self) -> None:
        """Test read_fault_registers without session."""
        manager = SessionManager()
        server = StdioMcpServer(manager)

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_fault_registers", "arguments": {}},
        }

        response = await server._handle_request(request)

        assert response["result"]["is_error"] is True
        assert "No active session" in response["result"]["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_read_fault_registers_with_session(self, tmp_path: Path) -> None:
        """Test read_fault_registers with mocked session."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()
        server = StdioMcpServer(manager)

        # Create mock session with required methods
        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        mock_session.read_memory = AsyncMock(
            side_effect=[
                bytes([0x02, 0x00, 0x00, 0x00]),  # CFSR
                bytes([0x00, 0x00, 0x00, 0x00]),  # HFSR
                bytes([0x00, 0x00, 0x00, 0x20]),  # MMFAR
                bytes([0x00, 0x00, 0x00, 0x00]),  # BFAR
            ]
        )

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            # Start session
            await manager.start_session(str(elf_file), cpu="cortex-m3")

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "read_fault_registers", "arguments": {}},
            }

            response = await server._handle_request(request)

            assert "is_error" not in response["result"]
            text = response["result"]["content"][0]["text"]
            assert "Fault Type:" in text

    @pytest.mark.asyncio
    async def test_read_exception_frame_with_session(self, tmp_path: Path) -> None:
        """Test read_exception_frame with mocked session."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()
        server = StdioMcpServer(manager)

        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        mock_session.read_registers = AsyncMock(return_value={"sp": 0x20001000})
        # Frame data: R0-R3, R12, LR, PC, xPSR (32 bytes)
        frame_data = (
            b"\x00\x00\x00\x00"  # R0
            b"\x01\x00\x00\x00"  # R1
            b"\x02\x00\x00\x00"  # R2
            b"\x03\x00\x00\x00"  # R3
            b"\x0c\x00\x00\x00"  # R12
            b"\x00\x10\x00\x08"  # LR
            b"\x34\x12\x00\x08"  # PC
            b"\x00\x00\x00\x01"  # xPSR
        )
        mock_session.read_memory = AsyncMock(return_value=frame_data)

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            await manager.start_session(str(elf_file), cpu="cortex-m3")

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "read_exception_frame", "arguments": {}},
            }

            response = await server._handle_request(request)

            assert "is_error" not in response["result"]
            text = response["result"]["content"][0]["text"]
            assert "Exception Frame" in text
            assert "Return Address" in text

    @pytest.mark.asyncio
    async def test_check_interrupt_priorities_with_session(
        self, tmp_path: Path
    ) -> None:
        """Test check_interrupt_priorities with mocked session."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()
        server = StdioMcpServer(manager)

        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        # NVIC reads for Cortex-M
        mock_session.read_memory = AsyncMock(
            return_value=bytes([0xFF, 0x00, 0x00, 0x00])
        )

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            await manager.start_session(str(elf_file), cpu="cortex-m3")

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "check_interrupt_priorities", "arguments": {}},
            }

            response = await server._handle_request(request)

            assert "is_error" not in response["result"]
            text = response["result"]["content"][0]["text"]
            assert "Interrupt Configuration" in text

    @pytest.mark.asyncio
    async def test_show_memory_protection_with_session(self, tmp_path: Path) -> None:
        """Test show_memory_protection with mocked session."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()
        server = StdioMcpServer(manager)

        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        # MPU TYPE and CTRL registers
        mock_session.read_memory = AsyncMock(
            return_value=bytes([0x00, 0x08, 0x00, 0x00])
        )

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            await manager.start_session(str(elf_file), cpu="cortex-m3")

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "show_memory_protection", "arguments": {}},
            }

            response = await server._handle_request(request)

            assert "is_error" not in response["result"]
            text = response["result"]["content"][0]["text"]
            assert "Memory Protection" in text

    @pytest.mark.asyncio
    async def test_analyze_crash_with_session(self, tmp_path: Path) -> None:
        """Test analyze_crash comprehensive tool."""
        elf_file = tmp_path / "test.elf"
        elf_file.touch()

        manager = SessionManager()
        server = StdioMcpServer(manager)

        mock_session = AsyncMock()
        mock_session.start = AsyncMock()
        mock_session.read_registers = AsyncMock(return_value={"sp": 0x20001000})
        # Frame data + fault registers
        frame_data = (
            b"\x00\x00\x00\x00"
            b"\x01\x00\x00\x00"
            b"\x02\x00\x00\x00"
            b"\x03\x00\x00\x00"
            b"\x0c\x00\x00\x00"
            b"\x00\x10\x00\x08"
            b"\x34\x12\x00\x08"
            b"\x00\x00\x00\x01"
        )
        # analyze_crash calls read_fault_state, decode_exception_frame, check_interrupt_config
        # Each needs multiple memory reads. Use return_value instead of side_effect
        # to handle arbitrary number of calls.
        mock_session.read_memory = AsyncMock(
            return_value=bytes([0x00, 0x00, 0x00, 0x00])
        )

        with patch(
            "unconcealer.mcp.session_manager.DebugSession",
            return_value=mock_session,
        ):
            await manager.start_session(str(elf_file), cpu="cortex-m3")

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "analyze_crash", "arguments": {}},
            }

            response = await server._handle_request(request)

            assert "is_error" not in response["result"]
            text = response["result"]["content"][0]["text"]
            assert "Crash Analysis" in text
            assert "Fault:" in text
