"""Stdio-based MCP server for Claude Desktop.

This module provides the main entry point for running the MCP server
over stdin/stdout, which is the transport Claude Desktop uses.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from unconcealer.mcp.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _text_response(text: str, is_error: bool = False) -> Dict[str, Any]:
    """Create a standard text response."""
    result: Dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


class StdioMcpServer:
    """MCP server that communicates over stdio.

    This server handles the MCP JSON-RPC protocol over stdin/stdout,
    providing debug tools to Claude Desktop.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        server_name: str = "unconcealer",
        server_version: str = "0.1.0",
    ):
        """Initialize the stdio server.

        Args:
            session_manager: Session manager for debug sessions
            server_name: Server name for MCP protocol
            server_version: Server version
        """
        self.session_manager = session_manager
        self.server_name = server_name
        self.server_version = server_version
        self._running = False

        # Define available tools
        self._tools = self._build_tool_definitions()

    def _build_tool_definitions(self) -> List[Dict[str, Any]]:
        """Build the list of tool definitions for MCP."""
        return [
            # Session management
            {
                "name": "start_session",
                "description": "Start a new debug session with QEMU and GDB.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "elf_path": {
                            "type": "string",
                            "description": "Path to ELF binary file",
                        },
                        "machine": {
                            "type": "string",
                            "description": "QEMU machine type (e.g., lm3s6965evb, mps2-an385)",
                            "default": "lm3s6965evb",
                        },
                        "cpu": {
                            "type": "string",
                            "description": "CPU type (e.g., cortex-m3, cortex-m4)",
                            "default": "cortex-m3",
                        },
                        "name": {
                            "type": "string",
                            "description": "Session name (auto-generated if not specified)",
                        },
                    },
                    "required": ["elf_path"],
                },
            },
            {
                "name": "stop_session",
                "description": "Stop a debug session and cleanup resources.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Session name to stop",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "list_sessions",
                "description": "List all active debug sessions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            # Register operations
            {
                "name": "read_registers",
                "description": "Read CPU registers. Returns all registers if none specified.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "registers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of register names (optional)",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name (uses current if not specified)",
                        },
                    },
                },
            },
            # Memory operations
            {
                "name": "read_memory",
                "description": "Read memory at address. Address can be hex (0x...) or symbol name.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Memory address (hex) or symbol name",
                        },
                        "length": {
                            "type": "integer",
                            "description": "Number of bytes to read",
                            "default": 64,
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["address"],
                },
            },
            {
                "name": "write_memory",
                "description": "Write bytes to memory. Data as hex string (e.g., 'deadbeef').",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "Memory address (hex) or symbol name",
                        },
                        "data": {
                            "type": "string",
                            "description": "Hex string of bytes to write",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["address", "data"],
                },
            },
            # Execution control
            {
                "name": "continue_execution",
                "description": "Continue execution until breakpoint, watchpoint, or exception.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "step",
                "description": "Single-step execution. Use instruction=true for assembly-level step.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "boolean",
                            "description": "Step by instruction (vs source line)",
                            "default": False,
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "step_over",
                "description": "Step over function calls.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "boolean",
                            "description": "Step by instruction",
                            "default": False,
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "halt",
                "description": "Halt execution immediately.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "reset",
                "description": "Reset the target to initial state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            # Breakpoints
            {
                "name": "set_breakpoint",
                "description": "Set breakpoint at function name, file:line, or *address.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "Breakpoint location (function, file:line, *address)",
                        },
                        "condition": {
                            "type": "string",
                            "description": "Breakpoint condition expression",
                        },
                        "temporary": {
                            "type": "boolean",
                            "description": "Delete after first hit",
                            "default": False,
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["location"],
                },
            },
            {
                "name": "delete_breakpoint",
                "description": "Delete a breakpoint by number.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "number": {
                            "type": "integer",
                            "description": "Breakpoint number",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["number"],
                },
            },
            # Stack & Analysis
            {
                "name": "backtrace",
                "description": "Get call stack backtrace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "max_frames": {
                            "type": "integer",
                            "description": "Maximum number of frames",
                            "default": 20,
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "evaluate",
                "description": "Evaluate a C expression in current context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "C expression to evaluate",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["expression"],
                },
            },
            # Snapshots
            {
                "name": "save_snapshot",
                "description": "Save VM state snapshot for later restoration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Snapshot name",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "load_snapshot",
                "description": "Restore VM to a previous snapshot.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Snapshot name",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                    "required": ["name"],
                },
            },
            # Architecture-specific tools
            {
                "name": "read_fault_registers",
                "description": "Read and decode fault/exception registers. For ARM Cortex-M: CFSR, HFSR, MMFAR, BFAR. For RISC-V: mcause, mtval, mepc.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "read_exception_frame",
                "description": "Parse the stacked exception/trap frame from the stack. Returns registers saved during exception entry.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "stack_pointer": {
                            "type": "string",
                            "description": "Stack pointer address (hex). Uses current SP if not specified.",
                        },
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "check_interrupt_priorities",
                "description": "Check interrupt controller configuration and detect issues. For ARM: checks NVIC priorities (e.g., PendSV vs SVCall). For RISC-V: checks PLIC/MIE configuration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "show_memory_protection",
                "description": "Display memory protection configuration. For ARM: shows MPU regions. For RISC-V: shows PMP entries.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
            {
                "name": "analyze_crash",
                "description": "Perform comprehensive crash analysis. Reads fault state, exception frame, and interrupt configuration to diagnose the crash cause.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session": {
                            "type": "string",
                            "description": "Session name",
                        },
                    },
                },
            },
        ]

    def _get_session(self, args: Dict[str, Any]):
        """Get session from args or current session."""
        session_name = args.get("session")
        if session_name:
            session = self.session_manager.get_session(session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")
            return session
        else:
            session = self.session_manager.get_current_session()
            if not session:
                raise ValueError("No active session. Use start_session first.")
            return session

    def _get_architecture(self, args: Dict[str, Any]):
        """Get architecture handler for session."""
        session_name = args.get("session")
        arch = self.session_manager.get_architecture(session_name)
        if not arch:
            raise ValueError("No active session. Use start_session first.")
        return arch

    async def _handle_tool_call(
        self, name: str, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle a tool call.

        Args:
            name: Tool name
            args: Tool arguments

        Returns:
            Tool result
        """
        try:
            # Session management tools
            if name == "start_session":
                info = await self.session_manager.start_session(
                    elf_path=args["elf_path"],
                    machine=args.get("machine", "lm3s6965evb"),
                    cpu=args.get("cpu", "cortex-m3"),
                    name=args.get("name"),
                )
                return _text_response(
                    f"Started session '{info.name}'\n"
                    f"  ELF: {info.elf_path}\n"
                    f"  Machine: {info.machine}\n"
                    f"  CPU: {info.cpu}\n"
                    f"  GDB Port: {info.gdb_port}"
                )

            elif name == "stop_session":
                success = await self.session_manager.stop_session(args["name"])
                if success:
                    return _text_response(f"Stopped session '{args['name']}'")
                else:
                    return _text_response(
                        f"Session '{args['name']}' not found", is_error=True
                    )

            elif name == "list_sessions":
                sessions = self.session_manager.list_sessions()
                if not sessions:
                    return _text_response("No active sessions")
                current = self.session_manager.get_current_name()
                lines = ["Active sessions:"]
                for info in sessions:
                    marker = "*" if info.name == current else " "
                    lines.append(
                        f"  {marker} {info.name}: {info.elf_path} "
                        f"({info.machine}/{info.cpu})"
                    )
                return _text_response("\n".join(lines))

            # Debug tools - need an active session
            session = self._get_session(args)

            if name == "read_registers":
                regs_list = args.get("registers")
                if regs_list is not None and len(regs_list) == 0:
                    regs_list = None
                regs = await session.read_registers(regs_list)
                lines = [f"{name:>4}: 0x{value:08x}" for name, value in sorted(regs.items())]
                return _text_response("\n".join(lines))

            elif name == "read_memory":
                addr_str = args["address"]
                length = args.get("length", 64)

                if addr_str.startswith("0x") or addr_str.startswith("0X"):
                    address = int(addr_str, 16)
                else:
                    result = await session.evaluate(f"&{addr_str}")
                    address = int(result.split()[0], 0)

                data = await session.read_memory(address, length)

                # Format as hex dump
                lines = []
                for i in range(0, len(data), 16):
                    chunk = data[i : i + 16]
                    hex_part = " ".join(f"{b:02x}" for b in chunk)
                    ascii_part = "".join(
                        chr(b) if 32 <= b < 127 else "." for b in chunk
                    )
                    lines.append(
                        f"0x{address + i:08x}: {hex_part:<48} {ascii_part}"
                    )
                return _text_response("\n".join(lines))

            elif name == "write_memory":
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

            elif name == "continue_execution":
                stop = await session.continue_execution()
                msg = f"Stopped: {stop.reason.value} at 0x{stop.address:08x}"
                if stop.signal_name:
                    msg += f" (signal: {stop.signal_name})"
                return _text_response(msg)

            elif name == "step":
                instruction = args.get("instruction", False)
                stop = await session.step(instruction=instruction)
                return _text_response(f"Stepped to 0x{stop.address:08x}")

            elif name == "step_over":
                instruction = args.get("instruction", False)
                stop = await session.step_over(instruction=instruction)
                return _text_response(f"Stepped to 0x{stop.address:08x}")

            elif name == "halt":
                await session.halt()
                return _text_response("Execution halted")

            elif name == "reset":
                success = await session.reset()
                if success:
                    return _text_response("Target reset")
                else:
                    return _text_response("Reset failed", is_error=True)

            elif name == "set_breakpoint":
                location = args["location"]
                condition = args.get("condition")
                temporary = args.get("temporary", False)
                bp = await session.set_breakpoint(location, condition, temporary)
                return _text_response(
                    f"Breakpoint {bp.number} at 0x{bp.address:08x} ({bp.location})"
                )

            elif name == "delete_breakpoint":
                number = args["number"]
                success = await session.delete_breakpoint(number)
                if success:
                    return _text_response(f"Deleted breakpoint {number}")
                else:
                    return _text_response(
                        f"Failed to delete breakpoint {number}", is_error=True
                    )

            elif name == "backtrace":
                max_frames = args.get("max_frames", 20)
                frames = await session.get_backtrace(max_frames)
                lines = []
                for frame in frames:
                    level = frame.get("level", 0)
                    addr = frame.get("addr", 0)
                    func = frame.get("func", "??")
                    file = frame.get("file")
                    line = frame.get("line")
                    loc = f"{file}:{line}" if file and line else ""
                    lines.append(f"#{level:<2} 0x{addr:08x} in {func} {loc}".strip())
                return _text_response("\n".join(lines))

            elif name == "evaluate":
                expr = args["expression"]
                result = await session.evaluate(expr)
                return _text_response(f"{expr} = {result}")

            elif name == "save_snapshot":
                snapshot_name = args["name"]
                success = await session.save_snapshot(snapshot_name)
                if success:
                    return _text_response(f"Saved snapshot '{snapshot_name}'")
                else:
                    return _text_response(
                        "Failed to save snapshot (requires QEMU snapshot support)",
                        is_error=True,
                    )

            elif name == "load_snapshot":
                snapshot_name = args["name"]
                success = await session.load_snapshot(snapshot_name)
                if success:
                    return _text_response(f"Restored snapshot '{snapshot_name}'")
                else:
                    return _text_response(
                        f"Failed to load snapshot '{snapshot_name}'", is_error=True
                    )

            # Architecture-specific tools
            elif name == "read_fault_registers":
                arch = self._get_architecture(args)
                fault = await arch.read_fault_state(session)
                lines = [f"Fault Type: {fault.fault_type}"]
                if fault.fault_address is not None:
                    lines.append(
                        f"Fault Address: 0x{fault.fault_address:08x}"
                        f" {'(valid)' if fault.is_valid else '(invalid)'}"
                    )
                lines.append("\nRaw Registers:")
                for reg, val in fault.raw_registers.items():
                    lines.append(f"  {reg}: 0x{val:08x}")
                if fault.decoded:
                    lines.append("\nDecoded:")
                    for bit, msg in fault.decoded.items():
                        lines.append(f"  {bit}: {msg}")
                return _text_response("\n".join(lines))

            elif name == "read_exception_frame":
                arch = self._get_architecture(args)
                sp_str = args.get("stack_pointer")
                sp = int(sp_str, 0) if sp_str else None
                frame = await arch.decode_exception_frame(session, sp)
                lines = [f"Exception Frame ({frame.frame_type}):"]
                lines.append(f"  Return Address: 0x{frame.return_address:08x}")
                lines.append(f"  Stack Pointer: 0x{frame.stack_pointer:08x}")
                lines.append("\nStacked Registers:")
                for reg, val in sorted(frame.registers.items()):
                    lines.append(f"  {reg:>6}: 0x{val:08x}")
                return _text_response("\n".join(lines))

            elif name == "check_interrupt_priorities":
                arch = self._get_architecture(args)
                analysis = await arch.check_interrupt_config(session)
                lines = ["Interrupt Configuration:"]
                if analysis.priorities:
                    lines.append("\nPriorities:")
                    for name_p, pri in sorted(analysis.priorities.items()):
                        lines.append(f"  {name_p}: {pri}")
                if analysis.enabled:
                    lines.append(f"\nEnabled: {len(analysis.enabled)} interrupts")
                    for info in analysis.enabled[:10]:  # Show first 10
                        lines.append(f"  {info.name}")
                if analysis.pending:
                    lines.append(f"\nPending: {len(analysis.pending)} interrupts")
                    for info in analysis.pending:
                        lines.append(f"  {info.name}")
                if analysis.warnings:
                    lines.append("\n⚠️  Warnings:")
                    for warn in analysis.warnings:
                        lines.append(f"  - {warn}")
                return _text_response("\n".join(lines))

            elif name == "show_memory_protection":
                arch = self._get_architecture(args)
                config = await arch.get_memory_protection(session)
                lines = [f"Memory Protection: {'Enabled' if config.enabled else 'Disabled'}"]
                lines.append(f"Default permissions: {config.default_permissions}")
                if config.regions:
                    lines.append(f"\nRegions ({len(config.regions)}):")
                    for region in config.regions:
                        lines.append(
                            f"  [{region.number}] 0x{region.base_address:08x} "
                            f"size={region.size:#x} {region.permissions}"
                        )
                else:
                    lines.append("\nNo regions configured")
                return _text_response("\n".join(lines))

            elif name == "analyze_crash":
                arch = self._get_architecture(args)
                analysis = await arch.analyze_crash(session)
                lines = [f"Crash Analysis ({analysis['architecture']})", "=" * 40]

                # Fault info
                fault = analysis["fault"]
                lines.append(f"\nFault: {fault['fault_type']}")
                if fault["fault_address"]:
                    lines.append(f"Address: {fault['fault_address']}")
                if fault["decoded"]:
                    for bit, msg in fault["decoded"].items():
                        lines.append(f"  {bit}: {msg}")

                # Exception frame
                frame = analysis["exception_frame"]
                lines.append(f"\nReturn Address: {frame['return_address']}")

                # Warnings
                interrupts = analysis["interrupts"]
                if interrupts["warnings"]:
                    lines.append("\n⚠️  Issues Detected:")
                    for warn in interrupts["warnings"]:
                        lines.append(f"  - {warn}")

                return _text_response("\n".join(lines))

            else:
                return _text_response(f"Unknown tool: {name}", is_error=True)

        except Exception as e:
            logger.exception(f"Error in tool {name}")
            return _text_response(f"Error: {e}", is_error=True)

    async def _handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an MCP request.

        Args:
            request: JSON-RPC request

        Returns:
            JSON-RPC response
        """
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {})

        logger.debug(f"Request: {method} {params}")

        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": self.server_name,
                            "version": self.server_version,
                        },
                        "capabilities": {
                            "tools": {},
                        },
                    },
                }

            elif method == "notifications/initialized":
                # No response needed for notifications
                return None

            elif method == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": self._tools,
                    },
                }

            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                result = await self._handle_tool_call(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

        except Exception as e:
            logger.exception(f"Error handling request: {method}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                },
            }

    async def run(self) -> None:
        """Run the server, reading from stdin and writing to stdout."""
        self._running = True
        logger.info(f"MCP server starting ({self.server_name} v{self.server_version})")

        # Read from stdin, write to stdout
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_event_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        # Get stdout write transport
        write_transport, _ = await loop.connect_write_pipe(
            asyncio.Protocol, sys.stdout
        )

        try:
            while self._running:
                # Read a line (JSON-RPC uses newline-delimited JSON)
                try:
                    line = await reader.readline()
                except asyncio.CancelledError:
                    break

                if not line:
                    break

                line = line.decode("utf-8").strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    continue

                response = await self._handle_request(request)

                if response is not None:
                    response_line = json.dumps(response) + "\n"
                    write_transport.write(response_line.encode("utf-8"))

        finally:
            # Cleanup
            await self.session_manager.stop_all()
            write_transport.close()
            logger.info("MCP server stopped")

    def stop(self) -> None:
        """Signal the server to stop."""
        self._running = False


async def run_stdio_server(
    gdb_path: Optional[str] = None,
    qemu_arm_path: Optional[str] = None,
    qemu_riscv32_path: Optional[str] = None,
    qemu_riscv64_path: Optional[str] = None,
    snapshot_dir: Optional[str] = None,
    verbose: bool = False,
) -> None:
    """Run the MCP server over stdio.

    Args:
        gdb_path: Path to GDB executable
        qemu_arm_path: Path to qemu-system-arm
        qemu_riscv32_path: Path to qemu-system-riscv32
        qemu_riscv64_path: Path to qemu-system-riscv64
        snapshot_dir: Directory for snapshot storage
        verbose: Enable verbose logging
    """
    # Configure logging to stderr (stdout is for MCP protocol)
    log_level = logging.DEBUG if verbose else logging.INFO
    log_level_str = os.environ.get("DEBUGGER_LOG_LEVEL", "INFO").upper()
    if log_level_str in ("DEBUG", "INFO", "WARNING", "ERROR"):
        log_level = getattr(logging, log_level_str)

    log_file = os.environ.get("DEBUGGER_LOG_FILE")
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(log_level)

    # Create session manager
    session_manager = SessionManager(
        gdb_path=gdb_path,
        qemu_arm_path=qemu_arm_path,
        qemu_riscv32_path=qemu_riscv32_path,
        qemu_riscv64_path=qemu_riscv64_path,
        snapshot_dir=snapshot_dir,
    )

    # Create and run server
    server = StdioMcpServer(session_manager)
    await server.run()
