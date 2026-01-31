"""Claude provider using the claude-agent-sdk with MCP support."""

from typing import Any, AsyncIterator

from unconcealer.agent.providers.base import (
    ModelProvider,
    CompletionChunk,
    ToolCall,
)


class ClaudeProvider(ModelProvider):
    """Provider using Claude Agent SDK with MCP server support.

    This provider uses the claude-agent-sdk which handles tool calling
    internally through MCP (Model Context Protocol) servers. Tools are
    registered with the MCP server rather than this provider directly.

    Example:
        from unconcealer.agent.tools import create_debug_server

        provider = ClaudeProvider(
            model="claude-sonnet-4-20250514",
            mcp_servers={"debug": create_debug_server(session)},
        )
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        mcp_servers: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
    ):
        """Initialize the Claude provider.

        Args:
            model: Claude model to use
            mcp_servers: MCP servers providing tools
            allowed_tools: List of tool names to allow (None = all)
        """
        super().__init__()

        try:
            from claude_agent_sdk import query as claude_query, ClaudeAgentOptions
            self._query = claude_query
            self._ClaudeAgentOptions = ClaudeAgentOptions
        except ImportError:
            raise ImportError(
                "claude-agent-sdk required for ClaudeProvider. "
                "Install with: pip install claude-agent-sdk"
            )

        self.model = model
        self.mcp_servers = mcp_servers or {}
        self.allowed_tools = allowed_tools

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream a completion from Claude.

        Note: Claude Agent SDK handles tool calling internally through MCP,
        so this method yields text chunks and a done signal. Tool calls
        are executed automatically by the SDK.

        Args:
            messages: Conversation history (last message used as prompt)
            system_prompt: System instructions
            **kwargs: Additional options for ClaudeAgentOptions

        Yields:
            CompletionChunk with text content
        """
        # Extract the last user message as the prompt
        # The SDK handles conversation differently than OpenAI
        if not messages:
            yield CompletionChunk(type="done")
            return

        prompt = messages[-1].get("content", "")

        options = self._ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            mcp_servers=self.mcp_servers,
            allowed_tools=self.allowed_tools,
            permission_mode="bypassPermissions",
            **kwargs,
        )

        async for message in self._query(prompt, options=options):
            if hasattr(message, "content"):
                for block in message.content:
                    if hasattr(block, "text"):
                        yield CompletionChunk(type="text", text=block.text)
                    # Tool calls are handled internally by the SDK

        yield CompletionChunk(type="done")

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        max_tool_rounds: int = 10,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Complete with tool execution (handled by Claude SDK).

        For ClaudeProvider, the SDK handles tool execution internally,
        so this is equivalent to complete().

        Args:
            messages: Conversation history
            system_prompt: System instructions
            max_tool_rounds: Ignored (SDK handles this)
            **kwargs: Additional options

        Yields:
            CompletionChunk for text content
        """
        # Claude SDK handles tool calling internally
        async for chunk in self.complete(messages, system_prompt, **kwargs):
            yield chunk


class ClaudeProviderWithTools(ModelProvider):
    """Claude provider that manages tools directly (without MCP).

    Use this when you want to use the provider abstraction's tool
    management instead of MCP servers.

    Note: This requires more setup but provides a consistent interface
    with other providers.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
    ):
        """Initialize Claude provider with direct tool management.

        Args:
            model: Claude model to use
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        super().__init__()

        try:
            import anthropic
            self.client = anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError:
            raise ImportError(
                "anthropic SDK required for ClaudeProviderWithTools. "
                "Install with: pip install anthropic"
            )

        self.model = model

    def _convert_tools_to_anthropic(self) -> list[dict[str, Any]]:
        """Convert tools to Anthropic format."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream a completion from Claude with tool support.

        Args:
            messages: Conversation history
            system_prompt: System instructions
            **kwargs: Additional parameters

        Yields:
            CompletionChunk with text or tool calls
        """
        tools = self._convert_tools_to_anthropic() if self._tools else None

        async with self.client.messages.stream(
            model=self.model,
            system=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=4096,
            **kwargs,
        ) as stream:
            current_tool_use: dict[str, Any] | None = None

            async for event in stream:
                if event.type == "content_block_start":
                    if hasattr(event.content_block, "type"):
                        if event.content_block.type == "tool_use":
                            current_tool_use = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": "",
                            }

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield CompletionChunk(type="text", text=event.delta.text)
                    elif hasattr(event.delta, "partial_json"):
                        if current_tool_use:
                            current_tool_use["input"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_use:
                        import json
                        try:
                            args = json.loads(current_tool_use["input"]) if current_tool_use["input"] else {}
                        except json.JSONDecodeError:
                            args = {}

                        yield CompletionChunk(
                            type="tool_call",
                            tool_call=ToolCall(
                                id=current_tool_use["id"],
                                name=current_tool_use["name"],
                                arguments=args,
                            ),
                        )
                        current_tool_use = None

                elif event.type == "message_stop":
                    yield CompletionChunk(type="done")
