"""Tests for Agent Orchestrator."""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from unconcealer.agent.orchestrator import (
    AgentOrchestrator,
    SessionMemory,
    Finding,
    SYSTEM_PROMPT,
)
from unconcealer.core.session import DebugSession


class TestFinding:
    """Test Finding dataclass."""

    def test_create_finding(self) -> None:
        """Test creating a finding."""
        finding = Finding(
            timestamp=datetime.now(),
            description="Stack overflow detected",
            evidence={"sp": 0x20000100, "stack_bottom": 0x20000200},
            severity="error"
        )
        assert finding.description == "Stack overflow detected"
        assert finding.severity == "error"
        assert "sp" in finding.evidence

    def test_finding_defaults(self) -> None:
        """Test finding default values."""
        finding = Finding(
            timestamp=datetime.now(),
            description="Test finding"
        )
        assert finding.evidence == {}
        assert finding.severity == "info"


class TestSessionMemory:
    """Test SessionMemory dataclass."""

    def test_initial_state(self) -> None:
        """Test initial memory state."""
        memory = SessionMemory()
        assert memory.snapshots == {}
        assert memory.breakpoints == []
        assert memory.findings == []
        assert memory.context == {}

    def test_add_finding(self) -> None:
        """Test adding findings."""
        memory = SessionMemory()
        memory.add_finding(
            "Found corruption at 0x20001000",
            evidence={"address": 0x20001000},
            severity="warning"
        )

        assert len(memory.findings) == 1
        assert memory.findings[0].description == "Found corruption at 0x20001000"
        assert memory.findings[0].severity == "warning"

    def test_get_context_summary_empty(self) -> None:
        """Test context summary when empty."""
        memory = SessionMemory()
        summary = memory.get_context_summary()
        assert summary == "No session context yet."

    def test_get_context_summary_with_data(self) -> None:
        """Test context summary with data."""
        memory = SessionMemory()
        memory.snapshots["before_crash"] = "State before HardFault"
        memory.breakpoints = [1, 2, 3]
        memory.add_finding("PC corrupted", severity="error")

        summary = memory.get_context_summary()
        assert "before_crash" in summary
        assert "1, 2, 3" in summary
        assert "PC corrupted" in summary
        assert "error" in summary


class TestAgentOrchestratorInstantiation:
    """Test orchestrator creation."""

    @pytest.fixture
    def mock_session(self) -> DebugSession:
        """Create a mock debug session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    def test_default_config(self, mock_session: DebugSession) -> None:
        """Test default configuration."""
        orchestrator = AgentOrchestrator(mock_session)

        assert orchestrator.session == mock_session
        assert orchestrator.model == "claude-sonnet-4-20250514"
        assert orchestrator.system_prompt == SYSTEM_PROMPT
        assert isinstance(orchestrator.memory, SessionMemory)

    def test_custom_model(self, mock_session: DebugSession) -> None:
        """Test custom model."""
        orchestrator = AgentOrchestrator(
            mock_session,
            model="claude-opus-4-20250514"
        )
        assert orchestrator.model == "claude-opus-4-20250514"

    def test_custom_system_prompt(self, mock_session: DebugSession) -> None:
        """Test custom system prompt."""
        custom_prompt = "You are a helpful debugger."
        orchestrator = AgentOrchestrator(
            mock_session,
            system_prompt=custom_prompt
        )
        assert orchestrator.system_prompt == custom_prompt


class TestAgentOrchestratorMemory:
    """Test orchestrator memory management."""

    @pytest.fixture
    def orchestrator(self) -> AgentOrchestrator:
        """Create orchestrator with mock session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return AgentOrchestrator(session)

    def test_add_finding(self, orchestrator: AgentOrchestrator) -> None:
        """Test adding a finding."""
        orchestrator.add_finding(
            "HardFault detected",
            evidence={"HFSR": 0x40000000},
            severity="critical"
        )

        assert len(orchestrator.findings) == 1
        assert orchestrator.findings[0].description == "HardFault detected"

    def test_record_snapshot(self, orchestrator: AgentOrchestrator) -> None:
        """Test recording a snapshot."""
        orchestrator.record_snapshot("initial", "Before running main()")

        assert "initial" in orchestrator.memory.snapshots
        assert orchestrator.memory.snapshots["initial"] == "Before running main()"

    def test_record_breakpoint(self, orchestrator: AgentOrchestrator) -> None:
        """Test recording breakpoints."""
        orchestrator.record_breakpoint(1)
        orchestrator.record_breakpoint(2)
        orchestrator.record_breakpoint(1)  # Duplicate

        assert orchestrator.memory.breakpoints == [1, 2]

    def test_clear_breakpoint(self, orchestrator: AgentOrchestrator) -> None:
        """Test clearing breakpoints."""
        orchestrator.record_breakpoint(1)
        orchestrator.record_breakpoint(2)
        orchestrator.clear_breakpoint(1)

        assert orchestrator.memory.breakpoints == [2]

    def test_context_management(self, orchestrator: AgentOrchestrator) -> None:
        """Test custom context."""
        orchestrator.set_context("target", "STM32F4")
        orchestrator.set_context("rtos", "FreeRTOS")

        assert orchestrator.get_context("target") == "STM32F4"
        assert orchestrator.get_context("rtos") == "FreeRTOS"
        assert orchestrator.get_context("missing", "default") == "default"


class TestAgentOrchestratorHistory:
    """Test conversation history management."""

    @pytest.fixture
    def orchestrator(self) -> AgentOrchestrator:
        """Create orchestrator with mock session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return AgentOrchestrator(session)

    def test_initial_history_empty(self, orchestrator: AgentOrchestrator) -> None:
        """Test history starts empty."""
        assert orchestrator.conversation_history == []

    def test_clear_history(self, orchestrator: AgentOrchestrator) -> None:
        """Test clearing history."""
        # Manually add to history for testing
        orchestrator._conversation_history.append(
            {"role": "user", "content": "test"}
        )
        orchestrator.clear_history()

        assert orchestrator.conversation_history == []

    def test_history_is_copy(self, orchestrator: AgentOrchestrator) -> None:
        """Test that history returns a copy."""
        orchestrator._conversation_history.append(
            {"role": "user", "content": "test"}
        )

        history = orchestrator.conversation_history
        history.append({"role": "user", "content": "another"})

        # Original should be unchanged
        assert len(orchestrator._conversation_history) == 1


class TestAgentOrchestratorOptions:
    """Test options building."""

    @pytest.fixture
    def orchestrator(self) -> AgentOrchestrator:
        """Create orchestrator with mock session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return AgentOrchestrator(session)

    def test_build_options(self, orchestrator: AgentOrchestrator) -> None:
        """Test options include debug tools."""
        options = orchestrator._build_options()

        assert "debug" in options.mcp_servers
        assert "read_registers" in options.allowed_tools
        assert "continue_execution" in options.allowed_tools
        assert options.permission_mode == "bypassPermissions"

    def test_build_options_custom(self, orchestrator: AgentOrchestrator) -> None:
        """Test custom options are passed through."""
        options = orchestrator._build_options(max_turns=5)

        assert options.max_turns == 5


class TestAgentOrchestratorQuery:
    """Test query functionality (with mocked Claude)."""

    @pytest.fixture
    def orchestrator(self) -> AgentOrchestrator:
        """Create orchestrator with mock session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return AgentOrchestrator(session)

    @pytest.mark.asyncio
    async def test_query_updates_history(
        self, orchestrator: AgentOrchestrator
    ) -> None:
        """Test that query updates conversation history."""
        # Mock the query function
        mock_message = Mock()
        mock_block = Mock()
        mock_block.text = "The PC is at 0x08001234"
        mock_message.content = [mock_block]

        async def mock_query_gen(*args, **kwargs):
            yield mock_message

        with patch("unconcealer.agent.orchestrator.query", mock_query_gen):
            response = await orchestrator.query("What is the PC?")

        assert response == "The PC is at 0x08001234"
        assert len(orchestrator.conversation_history) == 2
        assert orchestrator.conversation_history[0]["role"] == "user"
        assert orchestrator.conversation_history[0]["content"] == "What is the PC?"
        assert orchestrator.conversation_history[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_query_includes_context(
        self, orchestrator: AgentOrchestrator
    ) -> None:
        """Test that query includes session context."""
        orchestrator.record_snapshot("test", "Test snapshot")

        captured_prompt = None

        async def mock_query_gen(prompt, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            mock_message = Mock()
            mock_block = Mock()
            mock_block.text = "Response"
            mock_message.content = [mock_block]
            yield mock_message

        with patch("unconcealer.agent.orchestrator.query", mock_query_gen):
            await orchestrator.query("Test query")

        assert "test" in captured_prompt
        assert "Session Context" in captured_prompt


class TestAgentOrchestratorQueryStream:
    """Test streaming query functionality."""

    @pytest.fixture
    def orchestrator(self) -> AgentOrchestrator:
        """Create orchestrator with mock session."""
        session = Mock(spec=DebugSession)
        session._started = True
        return AgentOrchestrator(session)

    @pytest.mark.asyncio
    async def test_query_stream(self, orchestrator: AgentOrchestrator) -> None:
        """Test streaming query."""
        # Mock messages with chunks
        messages = []
        for text in ["Hello", " ", "World"]:
            mock_message = Mock()
            mock_block = Mock()
            mock_block.text = text
            mock_message.content = [mock_block]
            messages.append(mock_message)

        async def mock_query_gen(*args, **kwargs):
            for msg in messages:
                yield msg

        with patch("unconcealer.agent.orchestrator.query", mock_query_gen):
            chunks = []
            async for chunk in orchestrator.query_stream("Say hello"):
                chunks.append(chunk)

        assert chunks == ["Hello", " ", "World"]
        assert len(orchestrator.conversation_history) == 2
        assert orchestrator.conversation_history[1]["content"] == "Hello World"
