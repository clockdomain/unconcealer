"""Tests for Agent Tools."""

import pytest
from unittest.mock import Mock, AsyncMock

from unconcealer.agent.tools import (
    create_debug_tools,
    create_debug_server,
    _format_registers,
    _format_memory,
    _format_backtrace,
)
from unconcealer.core.session import DebugSession
from unconcealer.tools.gdb_bridge import StopReason, StopInfo, BreakpointInfo


class TestFormatters:
    """Test formatting helper functions."""

    def test_format_registers(self) -> None:
        """Test register formatting."""
        regs = {"pc": 0x08001234, "sp": 0x20010000, "r0": 0x00000000}
        result = _format_registers(regs)
        assert "pc: 0x08001234" in result
        assert "sp: 0x20010000" in result
        assert "r0: 0x00000000" in result

    def test_format_memory_hex(self) -> None:
        """Test memory formatting as hex."""
        data = bytes([0xde, 0xad, 0xbe, 0xef, 0x12, 0x34])
        result = _format_memory(data, 0x20000000)
        assert "0x20000000:" in result
        assert "de ad be ef 12 34" in result

    def test_format_memory_words(self) -> None:
        """Test memory formatting as words."""
        data = bytes([0xef, 0xbe, 0xad, 0xde])  # little-endian 0xdeadbeef
        result = _format_memory(data, 0x20000000, words=True)
        assert "0x20000000: 0xdeadbeef" in result

    def test_format_backtrace(self) -> None:
        """Test backtrace formatting."""
        frames = [
            {"level": 0, "addr": 0x08001234, "func": "main", "file": "main.c", "line": 42},
            {"level": 1, "addr": 0x08000100, "func": "Reset", "file": None, "line": None},
        ]
        result = _format_backtrace(frames)
        assert "#0" in result
        assert "main" in result
        assert "main.c:42" in result
        assert "#1" in result
        assert "Reset" in result


class TestCreateDebugTools:
    """Test debug tool creation."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    def test_creates_all_tools(self, mock_session: DebugSession) -> None:
        """Test that all expected tools are created."""
        tools = create_debug_tools(mock_session)

        tool_names = [t.name for t in tools]
        expected = [
            "read_registers",
            "read_memory",
            "write_memory",
            "continue_execution",
            "step",
            "step_over",
            "halt",
            "reset",
            "set_breakpoint",
            "delete_breakpoint",
            "backtrace",
            "evaluate",
            "save_snapshot",
            "load_snapshot",
        ]

        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_tools_have_descriptions(self, mock_session: DebugSession) -> None:
        """Test that all tools have descriptions."""
        tools = create_debug_tools(mock_session)

        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"


class TestReadRegisters:
    """Test read_registers tool."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_read_all_registers(self, mock_session: DebugSession) -> None:
        """Test reading all registers."""
        mock_session.read_registers = AsyncMock(
            return_value={"pc": 0x08001234, "sp": 0x20010000}
        )

        tools = create_debug_tools(mock_session)
        read_regs = next(t for t in tools if t.name == "read_registers")

        result = await read_regs.handler({"registers": []})

        assert "content" in result
        assert "pc: 0x08001234" in result["content"][0]["text"]
        mock_session.read_registers.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_read_specific_registers(self, mock_session: DebugSession) -> None:
        """Test reading specific registers."""
        mock_session.read_registers = AsyncMock(
            return_value={"pc": 0x08001234}
        )

        tools = create_debug_tools(mock_session)
        read_regs = next(t for t in tools if t.name == "read_registers")

        result = await read_regs.handler({"registers": ["pc"]})

        mock_session.read_registers.assert_called_once_with(["pc"])

    @pytest.mark.asyncio
    async def test_read_registers_error(self, mock_session: DebugSession) -> None:
        """Test error handling."""
        mock_session.read_registers = AsyncMock(side_effect=RuntimeError("Not connected"))

        tools = create_debug_tools(mock_session)
        read_regs = next(t for t in tools if t.name == "read_registers")

        result = await read_regs.handler({"registers": []})

        assert result.get("is_error") is True
        assert "Error" in result["content"][0]["text"]


class TestReadMemory:
    """Test read_memory tool."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_read_memory_hex_address(self, mock_session: DebugSession) -> None:
        """Test reading memory with hex address."""
        mock_session.read_memory = AsyncMock(return_value=b"\xde\xad\xbe\xef")

        tools = create_debug_tools(mock_session)
        read_mem = next(t for t in tools if t.name == "read_memory")

        result = await read_mem.handler({"address": "0x20000000", "length": 4})

        assert "content" in result
        assert "de ad be ef" in result["content"][0]["text"]
        mock_session.read_memory.assert_called_once_with(0x20000000, 4)


class TestContinueExecution:
    """Test continue_execution tool."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_continue_until_breakpoint(self, mock_session: DebugSession) -> None:
        """Test continuing until breakpoint."""
        stop_info = StopInfo(
            reason=StopReason.BREAKPOINT,
            address=0x08001234,
            breakpoint_number=1
        )
        mock_session.continue_execution = AsyncMock(return_value=stop_info)

        tools = create_debug_tools(mock_session)
        cont = next(t for t in tools if t.name == "continue_execution")

        result = await cont.handler({})

        assert "breakpoint-hit" in result["content"][0]["text"]
        assert "0x08001234" in result["content"][0]["text"]


class TestStep:
    """Test step tool."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_step_source(self, mock_session: DebugSession) -> None:
        """Test source-level step."""
        stop_info = StopInfo(reason=StopReason.STEP, address=0x08001238)
        mock_session.step = AsyncMock(return_value=stop_info)

        tools = create_debug_tools(mock_session)
        step_tool = next(t for t in tools if t.name == "step")

        result = await step_tool.handler({})

        mock_session.step.assert_called_once_with(instruction=False)

    @pytest.mark.asyncio
    async def test_step_instruction(self, mock_session: DebugSession) -> None:
        """Test instruction-level step."""
        stop_info = StopInfo(reason=StopReason.STEP, address=0x08001238)
        mock_session.step = AsyncMock(return_value=stop_info)

        tools = create_debug_tools(mock_session)
        step_tool = next(t for t in tools if t.name == "step")

        result = await step_tool.handler({"instruction": True})

        mock_session.step.assert_called_once_with(instruction=True)


class TestBreakpoints:
    """Test breakpoint tools."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_set_breakpoint(self, mock_session: DebugSession) -> None:
        """Test setting a breakpoint."""
        bp_info = BreakpointInfo(
            number=1,
            address=0x08001234,
            enabled=True,
            location="main"
        )
        mock_session.set_breakpoint = AsyncMock(return_value=bp_info)

        tools = create_debug_tools(mock_session)
        set_bp = next(t for t in tools if t.name == "set_breakpoint")

        result = await set_bp.handler({"location": "main"})

        assert "Breakpoint 1" in result["content"][0]["text"]
        assert "main" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_delete_breakpoint(self, mock_session: DebugSession) -> None:
        """Test deleting a breakpoint."""
        mock_session.delete_breakpoint = AsyncMock(return_value=True)

        tools = create_debug_tools(mock_session)
        del_bp = next(t for t in tools if t.name == "delete_breakpoint")

        result = await del_bp.handler({"number": 1})

        assert "Deleted breakpoint 1" in result["content"][0]["text"]


class TestBacktrace:
    """Test backtrace tool."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_backtrace(self, mock_session: DebugSession) -> None:
        """Test getting backtrace."""
        frames = [
            {"level": 0, "addr": 0x08001234, "func": "main", "file": "main.c", "line": 42},
        ]
        mock_session.get_backtrace = AsyncMock(return_value=frames)

        tools = create_debug_tools(mock_session)
        bt = next(t for t in tools if t.name == "backtrace")

        result = await bt.handler({"max_frames": 10})

        assert "main" in result["content"][0]["text"]
        mock_session.get_backtrace.assert_called_once_with(10)


class TestSnapshots:
    """Test snapshot tools."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    @pytest.mark.asyncio
    async def test_save_snapshot(self, mock_session: DebugSession) -> None:
        """Test saving snapshot."""
        mock_session.save_snapshot = AsyncMock(return_value=True)

        tools = create_debug_tools(mock_session)
        save = next(t for t in tools if t.name == "save_snapshot")

        result = await save.handler({"name": "test-snap"})

        assert "Saved snapshot 'test-snap'" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_load_snapshot(self, mock_session: DebugSession) -> None:
        """Test loading snapshot."""
        mock_session.load_snapshot = AsyncMock(return_value=True)

        tools = create_debug_tools(mock_session)
        load = next(t for t in tools if t.name == "load_snapshot")

        result = await load.handler({"name": "test-snap"})

        assert "Restored snapshot 'test-snap'" in result["content"][0]["text"]


class TestCreateDebugServer:
    """Test server creation."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    def test_creates_server(self, mock_session: DebugSession) -> None:
        """Test that server is created."""
        server = create_debug_server(mock_session)
        assert server is not None

    def test_custom_name_version(self, mock_session: DebugSession) -> None:
        """Test custom server name and version."""
        server = create_debug_server(
            mock_session,
            name="custom-debugger",
            version="2.0.0"
        )
        assert server is not None
