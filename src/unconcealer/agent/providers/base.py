"""Base types and protocol for model providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal


@dataclass
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class CompletionChunk:
    """A chunk of completion output."""

    type: Literal["text", "tool_call", "tool_result", "done"]
    text: str | None = None
    tool_call: ToolCall | None = None
    tool_result: str | None = None


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the model."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]


class ModelProvider(ABC):
    """Abstract base class for LLM providers with tool calling support.

    Implementations must provide:
    - complete(): Stream completions with optional tool calling
    - register_tool(): Register tools the model can call
    - call_tool(): Execute a tool call
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool that can be called by the model.

        Args:
            name: Tool name
            description: What the tool does
            parameters: JSON Schema for tool parameters
            handler: Async function to execute the tool
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas in OpenAI function format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool call and return the result.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Tool result as a string (JSON for complex results)
        """
        if tool_name not in self._tools:
            return f"Error: Unknown tool '{tool_name}'"

        tool = self._tools[tool_name]
        try:
            result = await tool.handler(**arguments)
            if isinstance(result, str):
                return result
            import json
            return json.dumps(result)
        except Exception as e:
            return f"Error calling {tool_name}: {e}"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream a completion with optional tool calling.

        Args:
            messages: Conversation history in OpenAI format
                [{"role": "user", "content": "..."}, ...]
            system_prompt: System instructions
            **kwargs: Provider-specific options

        Yields:
            CompletionChunk with text, tool calls, or tool results
        """
        ...

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        max_tool_rounds: int = 10,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Complete with automatic tool execution.

        This handles the tool-calling loop automatically:
        1. Get completion from model
        2. If model requests tool calls, execute them
        3. Feed results back to model
        4. Repeat until model produces text without tool calls

        Args:
            messages: Conversation history
            system_prompt: System instructions
            max_tool_rounds: Maximum tool-calling rounds
            **kwargs: Provider-specific options

        Yields:
            CompletionChunk for text and tool activity
        """
        current_messages = list(messages)
        rounds = 0

        while rounds < max_tool_rounds:
            rounds += 1
            pending_tool_calls: list[ToolCall] = []
            text_parts: list[str] = []

            async for chunk in self.complete(current_messages, system_prompt, **kwargs):
                if chunk.type == "text" and chunk.text:
                    text_parts.append(chunk.text)
                    yield chunk
                elif chunk.type == "tool_call" and chunk.tool_call:
                    pending_tool_calls.append(chunk.tool_call)
                    yield chunk
                elif chunk.type == "done":
                    break

            # If no tool calls, we're done
            if not pending_tool_calls:
                yield CompletionChunk(type="done")
                return

            # Execute tool calls and add results to messages
            assistant_content = "".join(text_parts) if text_parts else None
            current_messages.append({
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": str(tc.arguments),
                        },
                    }
                    for tc in pending_tool_calls
                ],
            })

            for tc in pending_tool_calls:
                result = await self.call_tool(tc.name, tc.arguments)
                yield CompletionChunk(type="tool_result", tool_result=result)
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        yield CompletionChunk(type="done")
