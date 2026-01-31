"""Debug tools for Claude Agent SDK.

This module provides MCP tools that wrap DebugSession methods, allowing
Claude to perform debugging operations on embedded firmware.

Example:
    from unconcealer.core.session import DebugSession
    from unconcealer.agent.tools import create_debug_server

    session = DebugSession(elf_path="firmware.elf")
    await session.start()

    server = create_debug_server(session)
    # Use server with ClaudeAgentOptions
"""

from typing import Any, Dict, List, Optional
from claude_agent_sdk import tool, create_sdk_mcp_server, SdkMcpTool

from unconcealer.core.session import DebugSession


def _text_response(text: str, is_error: bool = False) -> Dict[str, Any]:
    """Create a standard text response."""
    result: Dict[str, Any] = {
        "content": [{"type": "text", "text": text}]
    }
    if is_error:
        result["is_error"] = True
    return result


def _format_registers(regs: Dict[str, int]) -> str:
    """Format registers for display."""
    lines = []
    for name, value in sorted(regs.items()):
        lines.append(f"{name:>4}: 0x{value:08x}")
    return "\n".join(lines)


def _format_memory(data: bytes, address: int, words: bool = False) -> str:
    """Format memory dump for display."""
    lines = []
    if words:
        for i in range(0, len(data), 4):
            word = int.from_bytes(data[i:i+4], 'little')
            lines.append(f"0x{address + i:08x}: 0x{word:08x}")
    else:
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"0x{address + i:08x}: {hex_part:<48} {ascii_part}")
    return "\n".join(lines)


def _format_backtrace(frames: List[Dict[str, Any]]) -> str:
    """Format backtrace for display."""
    lines = []
    for frame in frames:
        level = frame.get("level", 0)
        addr = frame.get("addr", 0)
        func = frame.get("func", "??")
        file = frame.get("file")
        line = frame.get("line")

        loc = f"{file}:{line}" if file and line else ""
        lines.append(f"#{level:<2} 0x{addr:08x} in {func} {loc}".strip())
    return "\n".join(lines)


def create_debug_tools(session: DebugSession) -> List[SdkMcpTool[Any]]:
    """Create debug tools bound to a session.

    Args:
        session: Active debug session

    Returns:
        List of SdkMcpTool instances for use with create_sdk_mcp_server
    """

    # === Register Operations ===

    @tool(
        "read_registers",
        "Read CPU registers. Returns all registers if none specified.",
        {"registers": list}
    )
    async def read_registers(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            regs_list: Optional[List[str]] = args.get("registers")
            if regs_list is not None and len(regs_list) == 0:
                regs_list = None
            regs = await session.read_registers(regs_list)
            return _text_response(_format_registers(regs))
        except Exception as e:
            return _text_response(f"Error reading registers: {e}", is_error=True)

    # === Memory Operations ===

    @tool(
        "read_memory",
        "Read memory at address. Address can be hex (0x...) or symbol name.",
        {"address": str, "length": int}
    )
    async def read_memory(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            addr_str = args["address"]
            length = args.get("length", 64)

            # Parse address
            if addr_str.startswith("0x") or addr_str.startswith("0X"):
                address = int(addr_str, 16)
            else:
                # Try to evaluate as symbol
                result = await session.evaluate(f"&{addr_str}")
                address = int(result.split()[0], 0)

            data = await session.read_memory(address, length)
            return _text_response(_format_memory(data, address))
        except Exception as e:
            return _text_response(f"Error reading memory: {e}", is_error=True)

    @tool(
        "write_memory",
        "Write bytes to memory. Data as hex string (e.g., 'deadbeef').",
        {"address": str, "data": str}
    )
    async def write_memory(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            addr_str = args["address"]
            hex_data = args["data"].replace(" ", "")

            if addr_str.startswith("0x") or addr_str.startswith("0X"):
                address = int(addr_str, 16)
            else:
                result = await session.evaluate(f"&{addr_str}")
                address = int(result.split()[0], 0)

            data = bytes.fromhex(hex_data)
            success = await session.write_memory(address, data)

            if success:
                return _text_response(
                    f"Wrote {len(data)} bytes to 0x{address:08x}"
                )
            else:
                return _text_response("Write failed", is_error=True)
        except Exception as e:
            return _text_response(f"Error writing memory: {e}", is_error=True)

    # === Execution Control ===

    @tool(
        "continue_execution",
        "Continue execution until breakpoint, watchpoint, or exception.",
        {}
    )
    async def continue_execution(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            stop = await session.continue_execution()
            return _text_response(
                f"Stopped: {stop.reason.value} at 0x{stop.address:08x}"
                + (f" (signal: {stop.signal_name})" if stop.signal_name else "")
            )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "step",
        "Single-step execution. Use instruction=true for assembly-level step.",
        {"instruction": bool}
    )
    async def step(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            instruction = args.get("instruction", False)
            stop = await session.step(instruction=instruction)
            return _text_response(
                f"Stepped to 0x{stop.address:08x}"
            )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "step_over",
        "Step over function calls. Use instruction=true for assembly-level.",
        {"instruction": bool}
    )
    async def step_over(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            instruction = args.get("instruction", False)
            stop = await session.step_over(instruction=instruction)
            return _text_response(
                f"Stepped to 0x{stop.address:08x}"
            )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "halt",
        "Halt execution immediately.",
        {}
    )
    async def halt(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            await session.halt()
            return _text_response("Execution halted")
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "reset",
        "Reset the target to initial state.",
        {}
    )
    async def reset(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            success = await session.reset()
            if success:
                return _text_response("Target reset")
            else:
                return _text_response("Reset failed", is_error=True)
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    # === Breakpoints ===

    @tool(
        "set_breakpoint",
        "Set breakpoint at function name, file:line, or *address.",
        {"location": str, "condition": str, "temporary": bool}
    )
    async def set_breakpoint(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            location = args["location"]
            condition = args.get("condition")
            temporary = args.get("temporary", False)

            bp = await session.set_breakpoint(location, condition, temporary)
            return _text_response(
                f"Breakpoint {bp.number} at 0x{bp.address:08x} ({bp.location})"
            )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "delete_breakpoint",
        "Delete a breakpoint by number.",
        {"number": int}
    )
    async def delete_breakpoint(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            number = args["number"]
            success = await session.delete_breakpoint(number)
            if success:
                return _text_response(f"Deleted breakpoint {number}")
            else:
                return _text_response(
                    f"Failed to delete breakpoint {number}",
                    is_error=True
                )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    # === Stack & Analysis ===

    @tool(
        "backtrace",
        "Get call stack backtrace.",
        {"max_frames": int}
    )
    async def backtrace(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            max_frames = args.get("max_frames", 20)
            frames = await session.get_backtrace(max_frames)
            return _text_response(_format_backtrace(frames))
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "evaluate",
        "Evaluate a C expression in current context.",
        {"expression": str}
    )
    async def evaluate(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            expr = args["expression"]
            result = await session.evaluate(expr)
            return _text_response(f"{expr} = {result}")
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    # === Snapshots ===

    @tool(
        "save_snapshot",
        "Save VM state snapshot for later restoration.",
        {"name": str}
    )
    async def save_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            name = args["name"]
            success = await session.save_snapshot(name)
            if success:
                return _text_response(f"Saved snapshot '{name}'")
            else:
                return _text_response(
                    f"Failed to save snapshot (requires QEMU snapshot support)",
                    is_error=True
                )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    @tool(
        "load_snapshot",
        "Restore VM to a previous snapshot.",
        {"name": str}
    )
    async def load_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            name = args["name"]
            success = await session.load_snapshot(name)
            if success:
                return _text_response(f"Restored snapshot '{name}'")
            else:
                return _text_response(
                    f"Failed to load snapshot '{name}'",
                    is_error=True
                )
        except Exception as e:
            return _text_response(f"Error: {e}", is_error=True)

    return [
        read_registers,
        read_memory,
        write_memory,
        continue_execution,
        step,
        step_over,
        halt,
        reset,
        set_breakpoint,
        delete_breakpoint,
        backtrace,
        evaluate,
        save_snapshot,
        load_snapshot,
    ]


def create_debug_server(
    session: DebugSession,
    name: str = "unconcealer",
    version: str = "0.1.0"
) -> Any:
    """Create an MCP server with debug tools.

    Args:
        session: Active debug session
        name: Server name
        version: Server version

    Returns:
        McpSdkServerConfig for use with ClaudeAgentOptions

    Example:
        session = DebugSession(elf_path="firmware.elf")
        await session.start()

        server = create_debug_server(session)

        options = ClaudeAgentOptions(
            mcp_servers={"debug": server},
            allowed_tools=[
                "read_registers", "read_memory", "set_breakpoint",
                "continue_execution", "backtrace"
            ]
        )

        result = await query("What is the current PC?", options=options)
    """
    tools = create_debug_tools(session)
    return create_sdk_mcp_server(name=name, version=version, tools=tools)
