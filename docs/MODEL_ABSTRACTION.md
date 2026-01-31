# Model Abstraction Layer

This document describes the design for supporting multiple LLM providers in the unconcealer orchestrator.

## Current State

The orchestrator is currently coupled to Claude via `claude-agent-sdk`:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

class AgentOrchestrator:
    async def query(self, prompt: str) -> str:
        options = ClaudeAgentOptions(
            mcp_servers={"debug": self._server},
            model=self.model,
            ...
        )
        async for message in query(prompt, options=options):
            ...
```

## Proposed Design

### ModelProvider Protocol

Define a protocol that any LLM provider can implement:

```python
from typing import Protocol, AsyncIterator, Any

class ModelProvider(Protocol):
    """Interface for LLM providers with tool calling support."""

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream a completion with optional tool calling.

        Args:
            messages: Conversation history in OpenAI format
            system_prompt: System instructions
            tools: Tool definitions in OpenAI function format
            **kwargs: Provider-specific options

        Yields:
            CompletionChunk with text or tool calls
        """
        ...

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Execute a tool call and return the result.

        This is called by the orchestrator when the model requests a tool.
        """
        ...
```

### CompletionChunk

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class ToolCall:
    """A tool call requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class CompletionChunk:
    """A chunk of completion output."""
    type: Literal["text", "tool_call", "tool_result"]
    text: str | None = None
    tool_call: ToolCall | None = None
    tool_result: str | None = None
```

## Provider Implementations

### OpenAICompatibleProvider

Works with any OpenAI-compatible API (Azure, AWS Bedrock, LiteLLM, custom gateways):

```python
from openai import AsyncOpenAI

class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible APIs."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str = "gpt-4",
        default_headers: dict[str, str] | None = None,
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            default_headers=default_headers,
        )
        self.model = model
        self._tools: dict[str, Callable] = {}

    def register_tool(self, name: str, func: Callable, schema: dict) -> None:
        """Register a tool that can be called by the model."""
        self._tools[name] = func
        self._tool_schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters", {}),
            }
        })

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[CompletionChunk]:
        full_messages = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            tools=tools or self._tool_schemas,
            stream=True,
            **kwargs,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield CompletionChunk(type="text", text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    yield CompletionChunk(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=json.loads(tc.function.arguments),
                        )
                    )

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self._tools:
            return f"Error: Unknown tool {tool_name}"
        try:
            result = await self._tools[tool_name](**arguments)
            return json.dumps(result) if not isinstance(result, str) else result
        except Exception as e:
            return f"Error: {e}"
```

### ClaudeProvider

Wraps the existing `claude-agent-sdk`:

```python
from claude_agent_sdk import query, ClaudeAgentOptions

class ClaudeProvider:
    """Provider using Claude Agent SDK with MCP support."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        mcp_servers: dict | None = None,
    ):
        self.model = model
        self.mcp_servers = mcp_servers or {}

    async def complete(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[CompletionChunk]:
        # Build prompt from messages
        prompt = messages[-1]["content"] if messages else ""

        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            mcp_servers=self.mcp_servers,
            permission_mode="bypassPermissions",
            **kwargs,
        )

        async for message in query(prompt, options=options):
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        yield CompletionChunk(type="text", text=block.text)
```

## Updated Orchestrator

```python
class AgentOrchestrator:
    """Orchestrates debugging queries through an LLM provider."""

    def __init__(
        self,
        session: DebugSession,
        provider: ModelProvider,
        system_prompt: str | None = None,
    ):
        self.session = session
        self.provider = provider
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.memory = SessionMemory()
        self._conversation_history: list[dict] = []

        # Register debug tools with the provider
        self._register_tools()

    def _register_tools(self) -> None:
        """Register debugging tools with the provider."""
        tools = create_debug_tools(self.session)
        for tool in tools:
            self.provider.register_tool(
                name=tool.name,
                func=tool.handler,
                schema=tool.schema,
            )

    async def query(self, prompt: str) -> str:
        self._conversation_history.append({"role": "user", "content": prompt})

        response_parts = []
        async for chunk in self.provider.complete(
            messages=self._conversation_history,
            system_prompt=self.system_prompt,
        ):
            if chunk.type == "text" and chunk.text:
                response_parts.append(chunk.text)
            elif chunk.type == "tool_call" and chunk.tool_call:
                result = await self.provider.call_tool(
                    chunk.tool_call.name,
                    chunk.tool_call.arguments,
                )
                # Handle tool result...

        response = "".join(response_parts)
        self._conversation_history.append({"role": "assistant", "content": response})
        return response
```

## Usage Examples

### With Claude (current default)

```python
from unconcealer import DebugSession
from unconcealer.agent import AgentOrchestrator, ClaudeProvider

async with DebugSession(elf_path="firmware.elf") as session:
    provider = ClaudeProvider(model="claude-sonnet-4-20250514")
    orchestrator = AgentOrchestrator(session, provider=provider)
    response = await orchestrator.query("What is the PC?")
```

### With Corporate Gateway

```python
from unconcealer.agent import AgentOrchestrator, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    base_url="https://llm-gateway.company.com/v1",
    api_key=os.environ["COMPANY_LLM_KEY"],
    model="gpt-4-turbo",
    default_headers={"X-Team-ID": "firmware-debug"},
)

async with DebugSession(elf_path="firmware.elf") as session:
    orchestrator = AgentOrchestrator(session, provider=provider)
    response = await orchestrator.query("Analyze the stack")
```

### With Local Ollama

```python
provider = OpenAICompatibleProvider(
    base_url="http://localhost:11434/v1",
    model="llama3:70b",
)
```

## Tool Format Conversion

MCP tools use JSON Schema, which maps directly to OpenAI function format:

```python
def mcp_to_openai_tool(mcp_tool: Tool) -> dict:
    """Convert MCP tool definition to OpenAI function format."""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool.name,
            "description": mcp_tool.description,
            "parameters": mcp_tool.input_schema,
        }
    }
```

## Migration Path

1. **Phase 1**: Add `ModelProvider` protocol and `OpenAICompatibleProvider`
2. **Phase 2**: Wrap existing Claude code in `ClaudeProvider`
3. **Phase 3**: Update `AgentOrchestrator` to accept provider
4. **Phase 4**: Make provider configurable via CLI/config file

## Configuration

Add to `pyproject.toml` or config file:

```toml
[tool.unconcealer]
provider = "openai"  # or "claude"
base_url = "https://llm-gateway.company.com/v1"
model = "gpt-4-turbo"
```

Or via environment variables:

```bash
export UNCONCEALER_PROVIDER=openai
export UNCONCEALER_BASE_URL=https://llm-gateway.company.com/v1
export UNCONCEALER_MODEL=gpt-4-turbo
export UNCONCEALER_API_KEY=sk-...
```
