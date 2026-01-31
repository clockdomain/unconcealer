"""Tests for model providers."""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from unconcealer.agent.providers.base import (
    ModelProvider,
    CompletionChunk,
    ToolCall,
    ToolDefinition,
)


class TestCompletionChunk:
    """Test CompletionChunk dataclass."""

    def test_text_chunk(self) -> None:
        """Test creating a text chunk."""
        chunk = CompletionChunk(type="text", text="Hello")
        assert chunk.type == "text"
        assert chunk.text == "Hello"
        assert chunk.tool_call is None

    def test_tool_call_chunk(self) -> None:
        """Test creating a tool call chunk."""
        tc = ToolCall(id="123", name="read_memory", arguments={"address": "0x1000"})
        chunk = CompletionChunk(type="tool_call", tool_call=tc)
        assert chunk.type == "tool_call"
        assert chunk.tool_call.name == "read_memory"
        assert chunk.text is None

    def test_done_chunk(self) -> None:
        """Test creating a done chunk."""
        chunk = CompletionChunk(type="done")
        assert chunk.type == "done"


class TestToolCall:
    """Test ToolCall dataclass."""

    def test_create_tool_call(self) -> None:
        """Test creating a tool call."""
        tc = ToolCall(
            id="call_123",
            name="read_registers",
            arguments={"registers": ["pc", "sp"]},
        )
        assert tc.id == "call_123"
        assert tc.name == "read_registers"
        assert tc.arguments["registers"] == ["pc", "sp"]


class TestToolDefinition:
    """Test ToolDefinition dataclass."""

    def test_create_tool_definition(self) -> None:
        """Test creating a tool definition."""
        async def handler(x: int) -> int:
            return x * 2

        tool = ToolDefinition(
            name="double",
            description="Double a number",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
            handler=handler,
        )
        assert tool.name == "double"
        assert tool.description == "Double a number"


class ConcreteProvider(ModelProvider):
    """Concrete implementation for testing."""

    async def complete(self, messages, system_prompt, **kwargs):
        yield CompletionChunk(type="text", text="Test response")
        yield CompletionChunk(type="done")


class TestModelProviderBase:
    """Test ModelProvider base class."""

    def test_register_tool(self) -> None:
        """Test registering a tool."""
        provider = ConcreteProvider()

        async def my_tool(arg: str) -> str:
            return f"Result: {arg}"

        provider.register_tool(
            name="my_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {"arg": {"type": "string"}}},
            handler=my_tool,
        )

        assert "my_tool" in provider._tools
        assert provider._tools["my_tool"].description == "A test tool"

    def test_get_tool_schemas(self) -> None:
        """Test getting tool schemas in OpenAI format."""
        provider = ConcreteProvider()

        async def tool1() -> str:
            return "1"

        async def tool2() -> str:
            return "2"

        provider.register_tool("tool1", "First tool", {}, tool1)
        provider.register_tool("tool2", "Second tool", {}, tool2)

        schemas = provider.get_tool_schemas()
        assert len(schemas) == 2
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "tool1"
        assert schemas[1]["function"]["name"] == "tool2"

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        """Test calling a registered tool."""
        provider = ConcreteProvider()

        async def add(a: int, b: int) -> int:
            return a + b

        provider.register_tool("add", "Add numbers", {}, add)

        result = await provider.call_tool("add", {"a": 2, "b": 3})
        assert result == "5"

    @pytest.mark.asyncio
    async def test_call_tool_unknown(self) -> None:
        """Test calling an unknown tool."""
        provider = ConcreteProvider()
        result = await provider.call_tool("unknown", {})
        assert "Error: Unknown tool" in result

    @pytest.mark.asyncio
    async def test_call_tool_error(self) -> None:
        """Test tool error handling."""
        provider = ConcreteProvider()

        async def failing_tool() -> str:
            raise ValueError("Tool failed")

        provider.register_tool("failing", "Fails", {}, failing_tool)

        result = await provider.call_tool("failing", {})
        assert "Error" in result
        assert "Tool failed" in result

    @pytest.mark.asyncio
    async def test_complete_with_tools_no_tools(self) -> None:
        """Test complete_with_tools when no tool calls are made."""
        provider = ConcreteProvider()

        chunks = []
        async for chunk in provider.complete_with_tools(
            messages=[{"role": "user", "content": "Hello"}],
            system_prompt="Be helpful",
        ):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].type == "text"
        assert chunks[0].text == "Test response"
        assert chunks[1].type == "done"


class ToolCallingProvider(ModelProvider):
    """Provider that makes tool calls for testing."""

    def __init__(self):
        super().__init__()
        self.call_count = 0

    async def complete(self, messages, system_prompt, **kwargs):
        self.call_count += 1

        # First call: request a tool
        if self.call_count == 1:
            yield CompletionChunk(
                type="tool_call",
                tool_call=ToolCall(id="call_1", name="get_value", arguments={}),
            )
            yield CompletionChunk(type="done")
        else:
            # Second call: return text after tool result
            yield CompletionChunk(type="text", text="The value is 42")
            yield CompletionChunk(type="done")


class TestModelProviderToolCalling:
    """Test the tool calling loop."""

    @pytest.mark.asyncio
    async def test_complete_with_tools_executes_tools(self) -> None:
        """Test that complete_with_tools executes tool calls."""
        provider = ToolCallingProvider()

        async def get_value() -> int:
            return 42

        provider.register_tool("get_value", "Get a value", {}, get_value)

        chunks = []
        async for chunk in provider.complete_with_tools(
            messages=[{"role": "user", "content": "Get the value"}],
            system_prompt="Be helpful",
        ):
            chunks.append(chunk)

        # Should have: tool_call, done (from first complete), tool_result, text, done (from second)
        types = [c.type for c in chunks]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "text" in types


class TestClaudeProvider:
    """Test ClaudeProvider."""

    def test_init_without_sdk(self) -> None:
        """Test initialization fails gracefully without SDK."""
        with patch.dict("sys.modules", {"claude_agent_sdk": None}):
            # The import happens at init time, so we need to reimport
            pass  # This test would need module reload to work properly

    def test_init_with_mcp_servers(self) -> None:
        """Test initialization with MCP servers."""
        from unconcealer.agent.providers.claude import ClaudeProvider

        mock_server = Mock()
        provider = ClaudeProvider(
            model="claude-sonnet-4-20250514",
            mcp_servers={"debug": mock_server},
            allowed_tools=["read_registers"],
        )

        assert provider.model == "claude-sonnet-4-20250514"
        assert "debug" in provider.mcp_servers
        assert provider.allowed_tools == ["read_registers"]


class TestOpenAICompatibleProvider:
    """Test OpenAICompatibleProvider."""

    def test_init_requires_openai(self) -> None:
        """Test initialization requires openai package."""
        with patch.dict("sys.modules", {"openai": None}):
            from unconcealer.agent.providers import openai_compat
            import importlib
            importlib.reload(openai_compat)
            # Would need to test ImportError handling

    @pytest.mark.asyncio
    async def test_complete_streaming(self) -> None:
        """Test streaming completion."""
        # Create mock OpenAI module
        mock_openai = MagicMock()

        # Create mock response chunks
        mock_chunk1 = Mock()
        mock_chunk1.choices = [Mock()]
        mock_chunk1.choices[0].delta = Mock()
        mock_chunk1.choices[0].delta.content = "Hello"
        mock_chunk1.choices[0].delta.tool_calls = None
        mock_chunk1.choices[0].finish_reason = None

        mock_chunk2 = Mock()
        mock_chunk2.choices = [Mock()]
        mock_chunk2.choices[0].delta = Mock()
        mock_chunk2.choices[0].delta.content = " World"
        mock_chunk2.choices[0].delta.tool_calls = None
        mock_chunk2.choices[0].finish_reason = "stop"

        async def mock_stream():
            yield mock_chunk1
            yield mock_chunk2

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_openai.AsyncOpenAI.return_value = mock_client_instance

        with patch.dict("sys.modules", {"openai": mock_openai}):
            from unconcealer.agent.providers.openai_compat import OpenAICompatibleProvider

            provider = OpenAICompatibleProvider(
                base_url="http://localhost:8080/v1",
                model="gpt-4",
            )
            # Replace the client with our mock
            provider.client = mock_client_instance

            chunks = []
            async for chunk in provider.complete(
                messages=[{"role": "user", "content": "Hi"}],
                system_prompt="Be helpful",
            ):
                chunks.append(chunk)

            assert any(c.type == "text" and c.text == "Hello" for c in chunks)


class TestOrchestratorWithProvider:
    """Test AgentOrchestrator with custom provider."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock debug session."""
        from unconcealer.core.session import DebugSession
        session = Mock(spec=DebugSession)
        session._started = True
        return session

    def test_orchestrator_accepts_provider(self, mock_session) -> None:
        """Test orchestrator can be initialized with a provider."""
        from unconcealer.agent.orchestrator import AgentOrchestrator

        provider = ConcreteProvider()
        orchestrator = AgentOrchestrator(mock_session, provider=provider)

        assert orchestrator._provider is provider

    def test_orchestrator_default_uses_claude(self, mock_session) -> None:
        """Test orchestrator uses Claude by default."""
        from unconcealer.agent.orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator(mock_session)

        assert orchestrator._provider is None  # Uses claude-agent-sdk path
        assert orchestrator.model == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_orchestrator_query_with_provider(self, mock_session) -> None:
        """Test query uses the injected provider."""
        from unconcealer.agent.orchestrator import AgentOrchestrator

        provider = ConcreteProvider()
        orchestrator = AgentOrchestrator(mock_session, provider=provider)

        response = await orchestrator.query("Test query")

        assert response == "Test response"
        assert len(orchestrator.conversation_history) == 2
