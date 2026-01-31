"""Agent Orchestrator for debugging sessions.

The orchestrator manages the interaction between the user, the LLM provider,
and the debug session. It handles query processing, maintains session state,
and tracks findings during debugging.

Example:
    session = DebugSession(elf_path="firmware.elf")
    await session.start()

    orchestrator = AgentOrchestrator(session)
    response = await orchestrator.query("What is the current PC?")
    print(response)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, AsyncIterator, TYPE_CHECKING
from datetime import datetime

from claude_agent_sdk import query, ClaudeAgentOptions

from unconcealer.core.session import DebugSession
from unconcealer.agent.tools import create_debug_server

if TYPE_CHECKING:
    from unconcealer.agent.providers.base import ModelProvider


@dataclass
class Finding:
    """A debugging finding or observation."""
    timestamp: datetime
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"  # info, warning, error, critical


@dataclass
class SessionMemory:
    """Tracks session state across queries.

    Maintains context about the debugging session including snapshots,
    breakpoints, and findings discovered during investigation.
    """
    snapshots: Dict[str, str] = field(default_factory=dict)
    breakpoints: List[int] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def add_finding(
        self,
        description: str,
        evidence: Optional[Dict[str, Any]] = None,
        severity: str = "info"
    ) -> None:
        """Add a debugging finding."""
        self.findings.append(Finding(
            timestamp=datetime.now(),
            description=description,
            evidence=evidence or {},
            severity=severity
        ))

    def get_context_summary(self) -> str:
        """Get a summary of current context for the agent."""
        lines = []

        if self.snapshots:
            lines.append(f"Snapshots: {', '.join(self.snapshots.keys())}")

        if self.breakpoints:
            lines.append(f"Breakpoints: {self.breakpoints}")

        if self.findings:
            recent = self.findings[-3:]  # Last 3 findings
            lines.append("Recent findings:")
            for f in recent:
                lines.append(f"  - [{f.severity}] {f.description}")

        return "\n".join(lines) if lines else "No session context yet."


SYSTEM_PROMPT = """You are an expert embedded systems debugger with deep knowledge of ARM Cortex-M architecture, RTOS internals, and low-level debugging techniques.

You have access to a live debugging session with a QEMU-emulated target connected via GDB. Use the provided tools to investigate the firmware and help the user understand its behavior.

## Available Tools

- **read_registers**: Read CPU registers (pc, sp, lr, r0-r12, etc.)
- **read_memory**: Read memory at an address (hex or symbol name)
- **write_memory**: Write bytes to memory
- **continue_execution**: Continue until breakpoint or exception
- **step**: Single-step (source or instruction level)
- **step_over**: Step over function calls
- **halt**: Stop execution
- **reset**: Reset the target
- **set_breakpoint**: Set breakpoint at function/address
- **delete_breakpoint**: Remove a breakpoint
- **backtrace**: Get call stack
- **evaluate**: Evaluate C expression
- **save_snapshot**: Save VM state
- **load_snapshot**: Restore VM state

## Guidelines

1. **Be precise**: When reporting addresses, use hex format (0x...)
2. **Explain your reasoning**: Describe what you're checking and why
3. **Use tools actively**: Don't guess - read registers/memory to verify
4. **Build hypotheses**: Form theories and test them with evidence
5. **Consider ARM specifics**: Thumb bit, exception frames, NVIC, etc.

## ARM Cortex-M Knowledge

- PC bit 0 indicates Thumb mode (always 1 for Cortex-M)
- Exception frame: R0-R3, R12, LR, PC, xPSR pushed on stack
- CONTROL register: bit 1 = PSP/MSP selection, bit 0 = privilege
- Fault registers at 0xE000ED28 (CFSR), 0xE000ED2C (HFSR)
- Vector table at 0x00000000 (or VTOR offset)
"""


class AgentOrchestrator:
    """Orchestrates debugging queries through an LLM provider.

    The orchestrator manages the LLM provider, maintains session state,
    and processes user queries. By default it uses Claude via the claude-agent-sdk,
    but can be configured to use any provider implementing the ModelProvider protocol.

    Example:
        # Default: uses Claude with MCP tools
        async with DebugSession(elf_path="firmware.elf") as session:
            orchestrator = AgentOrchestrator(session)
            response = await orchestrator.query("What is the PC?")

        # Custom provider (e.g., corporate gateway)
        from unconcealer.agent.providers import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            base_url="https://llm-gateway.company.com/v1",
            model="gpt-4-turbo",
        )
        orchestrator = AgentOrchestrator(session, provider=provider)
    """

    def __init__(
        self,
        session: DebugSession,
        provider: Optional["ModelProvider"] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        """Initialize the orchestrator.

        Args:
            session: Active debug session
            provider: LLM provider (default: uses Claude via claude-agent-sdk)
            model: Model name (only used when provider is None)
            system_prompt: Custom system prompt (default: built-in)
        """
        self.session = session
        self.memory = SessionMemory()
        self.model = model or "claude-sonnet-4-20250514"
        self.system_prompt = system_prompt or SYSTEM_PROMPT

        # Store provider if provided
        self._provider = provider

        # Create MCP server with debug tools (used by default Claude path)
        self._server = create_debug_server(session)

        # Track conversation for context
        self._conversation_history: List[Dict[str, str]] = []

    def _build_options(self, **kwargs: Any) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions with debug tools."""
        # Tool names from our debug server
        allowed_tools = [
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

        return ClaudeAgentOptions(
            mcp_servers={"debug": self._server},
            allowed_tools=allowed_tools,
            system_prompt=self.system_prompt,
            model=self.model,
            permission_mode="bypassPermissions",  # Trust our tools
            **kwargs
        )

    async def query(self, prompt: str, **kwargs: Any) -> str:
        """Send a query to the LLM and get a response.

        Args:
            prompt: User's question or instruction
            **kwargs: Additional options for the provider

        Returns:
            LLM's response as a string
        """
        # Add context from session memory if available
        context = self.memory.get_context_summary()
        if context != "No session context yet.":
            full_prompt = f"{prompt}\n\n[Session Context]\n{context}"
        else:
            full_prompt = prompt

        response_parts: List[str] = []

        if self._provider is not None:
            # Use the injected provider
            messages = list(self._conversation_history)
            messages.append({"role": "user", "content": full_prompt})

            async for chunk in self._provider.complete_with_tools(
                messages=messages,
                system_prompt=self.system_prompt,
                **kwargs,
            ):
                if chunk.type == "text" and chunk.text:
                    response_parts.append(chunk.text)
        else:
            # Use default Claude path via claude-agent-sdk
            options = self._build_options(**kwargs)

            async for message in query(prompt=full_prompt, options=options):
                if hasattr(message, 'content'):
                    for block in message.content:
                        if hasattr(block, 'text'):
                            response_parts.append(block.text)

        response = "".join(response_parts)

        # Track in history
        self._conversation_history.append({"role": "user", "content": prompt})
        self._conversation_history.append({"role": "assistant", "content": response})

        return response

    async def query_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        """Stream a query response from the LLM.

        Args:
            prompt: User's question or instruction
            **kwargs: Additional options for the provider

        Yields:
            Response text chunks as they arrive
        """
        context = self.memory.get_context_summary()
        if context != "No session context yet.":
            full_prompt = f"{prompt}\n\n[Session Context]\n{context}"
        else:
            full_prompt = prompt

        response_parts: List[str] = []

        if self._provider is not None:
            # Use the injected provider
            messages = list(self._conversation_history)
            messages.append({"role": "user", "content": full_prompt})

            async for chunk in self._provider.complete_with_tools(
                messages=messages,
                system_prompt=self.system_prompt,
                **kwargs,
            ):
                if chunk.type == "text" and chunk.text:
                    response_parts.append(chunk.text)
                    yield chunk.text
        else:
            # Use default Claude path
            options = self._build_options(**kwargs)

            async for message in query(prompt=full_prompt, options=options):
                if hasattr(message, 'content'):
                    for block in message.content:
                        if hasattr(block, 'text'):
                            response_parts.append(block.text)
                            yield block.text

        # Track in history
        self._conversation_history.append({"role": "user", "content": prompt})
        self._conversation_history.append({
            "role": "assistant",
            "content": "".join(response_parts)
        })

    def add_finding(
        self,
        description: str,
        evidence: Optional[Dict[str, Any]] = None,
        severity: str = "info"
    ) -> None:
        """Record a debugging finding.

        Args:
            description: What was found
            evidence: Supporting data (registers, memory, etc.)
            severity: info, warning, error, or critical
        """
        self.memory.add_finding(description, evidence, severity)

    def record_snapshot(self, name: str, description: str = "") -> None:
        """Record that a snapshot was taken.

        Args:
            name: Snapshot name
            description: What state this captures
        """
        self.memory.snapshots[name] = description

    def record_breakpoint(self, bp_number: int) -> None:
        """Record a breakpoint number.

        Args:
            bp_number: Breakpoint ID from GDB
        """
        if bp_number not in self.memory.breakpoints:
            self.memory.breakpoints.append(bp_number)

    def clear_breakpoint(self, bp_number: int) -> None:
        """Remove a breakpoint from tracking.

        Args:
            bp_number: Breakpoint ID to remove
        """
        if bp_number in self.memory.breakpoints:
            self.memory.breakpoints.remove(bp_number)

    @property
    def findings(self) -> List[Finding]:
        """Get all findings."""
        return self.memory.findings

    @property
    def conversation_history(self) -> List[Dict[str, str]]:
        """Get conversation history."""
        return self._conversation_history.copy()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self._conversation_history.clear()

    def set_context(self, key: str, value: Any) -> None:
        """Set custom context for the session.

        Args:
            key: Context key
            value: Context value
        """
        self.memory.context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """Get custom context value.

        Args:
            key: Context key
            default: Default if not found

        Returns:
            Context value or default
        """
        return self.memory.context.get(key, default)
