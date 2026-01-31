"""OpenAI-compatible provider for corporate gateways and other APIs."""

from typing import Any, AsyncIterator
import json

from unconcealer.agent.providers.base import (
    ModelProvider,
    CompletionChunk,
    ToolCall,
)


class OpenAICompatibleProvider(ModelProvider):
    """Provider for OpenAI-compatible APIs.

    Works with:
    - OpenAI API directly
    - Azure OpenAI
    - AWS Bedrock (via OpenAI compatibility layer)
    - LiteLLM proxy
    - Corporate LLM gateways
    - Local Ollama (with OpenAI compatibility)

    Example:
        # Corporate gateway
        provider = OpenAICompatibleProvider(
            base_url="https://llm-gateway.company.com/v1",
            api_key=os.environ["COMPANY_LLM_KEY"],
            model="gpt-4-turbo",
            default_headers={"X-Team-ID": "firmware-debug"},
        )

        # Local Ollama
        provider = OpenAICompatibleProvider(
            base_url="http://localhost:11434/v1",
            model="llama3:70b",
        )
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str = "gpt-4",
        default_headers: dict[str, str] | None = None,
        **client_kwargs: Any,
    ):
        """Initialize the OpenAI-compatible provider.

        Args:
            base_url: Base URL of the API (e.g., https://api.openai.com/v1)
            api_key: API key for authentication
            model: Model name/ID to use
            default_headers: Additional headers to send with requests
            **client_kwargs: Additional arguments for AsyncOpenAI client
        """
        super().__init__()

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "OpenAI SDK required for OpenAICompatibleProvider. "
                "Install with: pip install openai"
            )

        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "dummy",  # Some endpoints don't need a key
            default_headers=default_headers,
            **client_kwargs,
        )
        self.model = model

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream a completion from the OpenAI-compatible API.

        Args:
            messages: Conversation history
            system_prompt: System instructions
            **kwargs: Additional parameters for the API call

        Yields:
            CompletionChunk with text or tool calls
        """
        # Build full message list with system prompt
        full_messages = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        # Get tool schemas if we have tools registered
        tools = self.get_tool_schemas() if self._tools else None

        # Create streaming completion
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            tools=tools,
            stream=True,
            **kwargs,
        )

        # Track partial tool calls across chunks
        current_tool_calls: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Handle text content
            if delta.content:
                yield CompletionChunk(type="text", text=delta.content)

            # Handle tool calls (streamed in pieces)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index

                    if idx not in current_tool_calls:
                        current_tool_calls[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }

                    if tc.id:
                        current_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            current_tool_calls[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            current_tool_calls[idx]["arguments"] += tc.function.arguments

            # Check for finish reason
            if chunk.choices[0].finish_reason:
                # Emit any completed tool calls
                for tc_data in current_tool_calls.values():
                    if tc_data["name"] and tc_data["id"]:
                        try:
                            args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {}

                        yield CompletionChunk(
                            type="tool_call",
                            tool_call=ToolCall(
                                id=tc_data["id"],
                                name=tc_data["name"],
                                arguments=args,
                            ),
                        )

                yield CompletionChunk(type="done")
                return

    async def complete_non_streaming(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        **kwargs: Any,
    ) -> tuple[str, list[ToolCall]]:
        """Non-streaming completion for simpler use cases.

        Args:
            messages: Conversation history
            system_prompt: System instructions
            **kwargs: Additional parameters

        Returns:
            Tuple of (response_text, tool_calls)
        """
        full_messages = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        tools = self.get_tool_schemas() if self._tools else None

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            tools=tools,
            stream=False,
            **kwargs,
        )

        choice = response.choices[0]
        text = choice.message.content or ""

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        return text, tool_calls
