#!/usr/bin/env python3
"""Single-command interface for Claude Code integration.

This module provides a command-line wrapper that allows Claude Code to
invoke debugging tools via Bash. Sessions persist between invocations
by keeping QEMU running and storing state in a JSON file.

Usage:
    unconcealer-cmd start_session /path/to/firmware.elf
    unconcealer-cmd read_registers
    unconcealer-cmd set_breakpoint main
    unconcealer-cmd continue_execution
    unconcealer-cmd analyze_crash
    unconcealer-cmd stop_session

Session state is stored in /tmp/unconcealer-cmd/sessions/
"""

import argparse
import asyncio
import json
import os
import signal
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Session state directory
SESSION_DIR = Path(os.environ.get("UNCONCEALER_SESSION_DIR", "/tmp/unconcealer-cmd/sessions"))


@dataclass
class SessionState:
    """Persisted session state."""
    name: str
    elf_path: str
    machine: str
    cpu: str
    gdb_port: int
    qmp_port: int
    qemu_pid: int
    architecture: str
    created_at: str

    def to_file(self, path: Path) -> None:
        """Save state to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def from_file(cls, path: Path) -> "SessionState":
        """Load state from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


def get_session_file(name: str = "default") -> Path:
    """Get path to session state file."""
    return SESSION_DIR / f"{name}.json"


def list_sessions() -> List[str]:
    """List available session names."""
    if not SESSION_DIR.exists():
        return []
    return [f.stem for f in SESSION_DIR.glob("*.json")]


def is_process_running(pid: int) -> bool:
    """Check if a process is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


async def start_session(
    elf_path: str,
    machine: str = "lm3s6965evb",
    cpu: str = "cortex-m3",
    session_name: str = "default",
) -> Dict[str, Any]:
    """Start a new debug session."""
    from unconcealer.tools.qemu_control import QEMUConfig, QEMUController
    from unconcealer.tools.gdb_bridge import GDBBridge
    from unconcealer.arch import detect_architecture

    # Check for existing session
    session_file = get_session_file(session_name)
    if session_file.exists():
        state = SessionState.from_file(session_file)
        if is_process_running(state.qemu_pid):
            return {
                "error": f"Session '{session_name}' already exists (QEMU PID {state.qemu_pid}). "
                         f"Use stop_session first or choose a different session name."
            }
        # Clean up stale session file
        session_file.unlink()

    # Validate ELF
    elf = Path(elf_path).expanduser().resolve()
    if not elf.exists():
        return {"error": f"ELF file not found: {elf}"}

    # Allocate ports (simple strategy: use session hash)
    base_port = 1234 + (hash(session_name) % 1000)
    gdb_port = base_port
    qmp_port = base_port + 1000

    # Determine QEMU path
    cpu_lower = cpu.lower()
    machine_lower = machine.lower()
    if "rv64" in cpu_lower or "riscv64" in machine_lower:
        qemu_path = os.environ.get("DEBUGGER_QEMU_RISCV64_PATH", "qemu-system-riscv64")
    elif "rv32" in cpu_lower or "riscv32" in machine_lower or "sifive" in machine_lower:
        qemu_path = os.environ.get("DEBUGGER_QEMU_RISCV32_PATH", "qemu-system-riscv32")
    else:
        qemu_path = os.environ.get("DEBUGGER_QEMU_ARM_PATH", "qemu-system-arm")

    # Start QEMU
    config = QEMUConfig(
        qemu_path=qemu_path,
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
        qmp_port=qmp_port,
    )

    qemu = QEMUController(config)
    try:
        await qemu.start(str(elf))
    except Exception as e:
        return {"error": f"Failed to start QEMU: {e}"}

    # Get QEMU PID
    qemu_pid = qemu.process.pid if qemu.process else 0

    # Connect GDB to verify it works
    gdb_path = os.environ.get("DEBUGGER_GDB_PATH", "gdb-multiarch")
    gdb = GDBBridge(gdb_path)
    try:
        await gdb.start()
        await gdb.load_symbols(str(elf))
        await gdb.connect(port=gdb_port)
        await gdb.close()
    except Exception as e:
        # Kill QEMU if GDB fails
        if qemu.process:
            qemu.process.terminate()
        return {"error": f"Failed to connect GDB: {e}"}

    # Detect architecture
    arch_name = detect_architecture(cpu, machine)

    # Save session state
    state = SessionState(
        name=session_name,
        elf_path=str(elf),
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
        qmp_port=qmp_port,
        qemu_pid=qemu_pid,
        architecture=arch_name,
        created_at=datetime.now().isoformat(),
    )
    state.to_file(session_file)

    # Don't close QEMU - leave it running!
    # Just disconnect our references so the process continues
    qemu.process = None
    qemu.qmp_socket = None

    return {
        "status": "started",
        "session": session_name,
        "elf_path": str(elf),
        "machine": machine,
        "cpu": cpu,
        "gdb_port": gdb_port,
        "qemu_pid": qemu_pid,
        "architecture": arch_name,
    }


async def stop_session(session_name: str = "default") -> Dict[str, Any]:
    """Stop a debug session."""
    session_file = get_session_file(session_name)
    if not session_file.exists():
        return {"error": f"Session '{session_name}' not found"}

    state = SessionState.from_file(session_file)

    # Kill QEMU
    if is_process_running(state.qemu_pid):
        try:
            os.kill(state.qemu_pid, signal.SIGTERM)
            # Wait a bit for graceful shutdown
            await asyncio.sleep(0.5)
            if is_process_running(state.qemu_pid):
                os.kill(state.qemu_pid, signal.SIGKILL)
        except Exception as e:
            pass  # Process may have already exited

    # Remove session file
    session_file.unlink()

    return {"status": "stopped", "session": session_name}


async def get_session_context(session_name: str = "default"):
    """Get session state and reconnect GDB.

    Returns (state, gdb) tuple. Caller must close gdb when done.
    """
    from unconcealer.tools.gdb_bridge import GDBBridge

    session_file = get_session_file(session_name)
    if not session_file.exists():
        raise ValueError(f"Session '{session_name}' not found. Use start_session first.")

    state = SessionState.from_file(session_file)

    if not is_process_running(state.qemu_pid):
        # Clean up stale session
        session_file.unlink()
        raise ValueError(f"Session '{session_name}' QEMU process not running. Session cleaned up.")

    # Connect GDB
    gdb_path = os.environ.get("DEBUGGER_GDB_PATH", "gdb-multiarch")
    gdb = GDBBridge(gdb_path)
    await gdb.start()
    await gdb.load_symbols(state.elf_path)
    await gdb.connect(port=state.gdb_port)

    return state, gdb


async def execute_tool(tool_name: str, args: Dict[str, Any], session_name: str = "default") -> Dict[str, Any]:
    """Execute a debugging tool."""
    from unconcealer.arch import get_architecture

    # Session management tools
    if tool_name == "start_session":
        return await start_session(
            elf_path=args.get("elf_path", ""),
            machine=args.get("machine", "lm3s6965evb"),
            cpu=args.get("cpu", "cortex-m3"),
            session_name=session_name,
        )

    if tool_name == "stop_session":
        return await stop_session(session_name)

    if tool_name == "list_sessions":
        sessions = list_sessions()
        if not sessions:
            return {"sessions": [], "message": "No active sessions"}
        result = []
        for name in sessions:
            try:
                state = SessionState.from_file(get_session_file(name))
                running = is_process_running(state.qemu_pid)
                result.append({
                    "name": name,
                    "elf_path": state.elf_path,
                    "machine": state.machine,
                    "cpu": state.cpu,
                    "running": running,
                })
            except Exception:
                pass
        return {"sessions": result}

    # Tools that need an active session
    try:
        state, gdb = await get_session_context(session_name)
    except ValueError as e:
        return {"error": str(e)}

    try:
        # Register operations
        if tool_name == "read_registers":
            regs_list = args.get("registers")
            if regs_list is not None and len(regs_list) == 0:
                regs_list = None
            regs = await gdb.read_registers(regs_list)
            return {"registers": {name: f"0x{val:08x}" for name, val in sorted(regs.items())}}

        # Memory operations
        elif tool_name == "read_memory":
            addr_str = args.get("address", "0")
            length = args.get("length", 64)

            if addr_str.startswith("0x") or addr_str.startswith("0X"):
                address = int(addr_str, 16)
            else:
                result = await gdb.evaluate(f"&{addr_str}")
                address = int(result.value.split()[0], 0)

            data = await gdb.read_memory(address, length)

            # Format as hex dump
            lines = []
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                hex_part = " ".join(f"{b:02x}" for b in chunk)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                lines.append(f"0x{address + i:08x}: {hex_part:<48} {ascii_part}")
            return {"memory": "\n".join(lines)}

        elif tool_name == "write_memory":
            addr_str = args.get("address", "0")
            hex_data = args.get("data", "").replace(" ", "")

            if addr_str.startswith("0x") or addr_str.startswith("0X"):
                address = int(addr_str, 16)
            else:
                result = await gdb.evaluate(f"&{addr_str}")
                address = int(result.value.split()[0], 0)

            data = bytes.fromhex(hex_data)
            success = await gdb.write_memory(address, data)
            return {"status": "written" if success else "failed", "bytes": len(data), "address": f"0x{address:08x}"}

        # Execution control
        elif tool_name == "continue_execution":
            stop = await gdb.continue_execution()
            return {
                "status": "stopped",
                "reason": stop.reason.value,
                "address": f"0x{stop.address:08x}",
                "signal": stop.signal_name,
            }

        elif tool_name == "step":
            instruction = args.get("instruction", False)
            stop = await gdb.step(instruction=instruction)
            return {"status": "stepped", "address": f"0x{stop.address:08x}"}

        elif tool_name == "step_over":
            instruction = args.get("instruction", False)
            stop = await gdb.step_over(instruction=instruction)
            return {"status": "stepped", "address": f"0x{stop.address:08x}"}

        elif tool_name == "halt":
            await gdb.halt()
            return {"status": "halted"}

        # Breakpoints
        elif tool_name == "set_breakpoint":
            location = args.get("location", "main")
            condition = args.get("condition")
            temporary = args.get("temporary", False)
            bp = await gdb.set_breakpoint(location, condition, temporary)
            return {
                "status": "set",
                "number": bp.number,
                "address": f"0x{bp.address:08x}",
                "location": bp.location,
            }

        elif tool_name == "delete_breakpoint":
            number = args.get("number", 1)
            success = await gdb.delete_breakpoint(number)
            return {"status": "deleted" if success else "failed", "number": number}

        # Analysis
        elif tool_name == "backtrace":
            max_frames = args.get("max_frames", 20)
            frames = await gdb.get_backtrace(max_frames)
            lines = []
            for frame in frames:
                level = frame.get("level", 0)
                addr = frame.get("addr", 0)
                func = frame.get("func", "??")
                file = frame.get("file")
                line_no = frame.get("line")
                loc = f"{file}:{line_no}" if file and line_no else ""
                lines.append(f"#{level:<2} 0x{addr:08x} in {func} {loc}".strip())
            return {"backtrace": "\n".join(lines)}

        elif tool_name == "evaluate":
            expr = args.get("expression", "0")
            result = await gdb.evaluate(expr)
            return {"expression": expr, "value": result.value}

        # Architecture-specific tools
        elif tool_name == "read_fault_registers":
            arch = get_architecture(state.architecture)
            if not arch:
                return {"error": f"Unknown architecture: {state.architecture}"}

            # Create a minimal session-like object for the arch tools
            class SessionProxy:
                def __init__(self, gdb_bridge):
                    self.gdb = gdb_bridge
                async def read_memory(self, addr, length):
                    return await self.gdb.read_memory(addr, length)
                async def read_memory_word(self, addr):
                    return await self.gdb.read_memory_word(addr)
                async def read_registers(self, names=None):
                    return await self.gdb.read_registers(names)
                async def read_register(self, name):
                    return await self.gdb.read_register(name)

            proxy = SessionProxy(gdb)
            fault = await arch.read_fault_state(proxy)

            result = {
                "fault_type": fault.fault_type,
                "fault_address": f"0x{fault.fault_address:08x}" if fault.fault_address else None,
                "is_valid": fault.is_valid,
                "raw_registers": {k: f"0x{v:08x}" for k, v in fault.raw_registers.items()},
                "decoded": fault.decoded,
            }
            return result

        elif tool_name == "analyze_crash":
            arch = get_architecture(state.architecture)
            if not arch:
                return {"error": f"Unknown architecture: {state.architecture}"}

            class SessionProxy:
                def __init__(self, gdb_bridge):
                    self.gdb = gdb_bridge
                async def read_memory(self, addr, length):
                    return await self.gdb.read_memory(addr, length)
                async def read_memory_word(self, addr):
                    return await self.gdb.read_memory_word(addr)
                async def read_registers(self, names=None):
                    return await self.gdb.read_registers(names)
                async def read_register(self, name):
                    return await self.gdb.read_register(name)

            proxy = SessionProxy(gdb)
            analysis = await arch.analyze_crash(proxy)
            return analysis

        elif tool_name == "read_exception_frame":
            arch = get_architecture(state.architecture)
            if not arch:
                return {"error": f"Unknown architecture: {state.architecture}"}

            class SessionProxy:
                def __init__(self, gdb_bridge):
                    self.gdb = gdb_bridge
                async def read_memory(self, addr, length):
                    return await self.gdb.read_memory(addr, length)
                async def read_memory_word(self, addr):
                    return await self.gdb.read_memory_word(addr)
                async def read_registers(self, names=None):
                    return await self.gdb.read_registers(names)
                async def read_register(self, name):
                    return await self.gdb.read_register(name)

            proxy = SessionProxy(gdb)
            sp_str = args.get("stack_pointer")
            sp = int(sp_str, 0) if sp_str else None
            frame = await arch.decode_exception_frame(proxy, sp)

            return {
                "frame_type": frame.frame_type,
                "return_address": f"0x{frame.return_address:08x}",
                "stack_pointer": f"0x{frame.stack_pointer:08x}",
                "registers": {k: f"0x{v:08x}" for k, v in frame.registers.items()},
            }

        elif tool_name == "check_interrupt_priorities":
            arch = get_architecture(state.architecture)
            if not arch:
                return {"error": f"Unknown architecture: {state.architecture}"}

            class SessionProxy:
                def __init__(self, gdb_bridge):
                    self.gdb = gdb_bridge
                async def read_memory(self, addr, length):
                    return await self.gdb.read_memory(addr, length)
                async def read_memory_word(self, addr):
                    return await self.gdb.read_memory_word(addr)
                async def read_registers(self, names=None):
                    return await self.gdb.read_registers(names)
                async def read_register(self, name):
                    return await self.gdb.read_register(name)

            proxy = SessionProxy(gdb)
            analysis = await arch.check_interrupt_config(proxy)

            return {
                "priorities": analysis.priorities,
                "enabled_count": len(analysis.enabled),
                "pending_count": len(analysis.pending),
                "warnings": analysis.warnings,
            }

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    finally:
        # Always close GDB connection
        await gdb.close()


def format_output(result: Dict[str, Any]) -> str:
    """Format result for terminal output."""
    if "error" in result:
        return f"ERROR: {result['error']}"

    # Special formatting for certain tools
    if "registers" in result:
        lines = [f"{name:>6}: {val}" for name, val in result["registers"].items()]
        return "\n".join(lines)

    if "memory" in result:
        return result["memory"]

    if "backtrace" in result:
        return result["backtrace"]

    # Default: pretty-print JSON
    return json.dumps(result, indent=2)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Single-command debugging interface for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  unconcealer-cmd start_session /path/to/firmware.elf
  unconcealer-cmd --session myfw start_session /path/to/firmware.elf --machine lm3s6965evb
  unconcealer-cmd read_registers
  unconcealer-cmd set_breakpoint main
  unconcealer-cmd continue_execution
  unconcealer-cmd read_memory 0x20000000 --length 64
  unconcealer-cmd analyze_crash
  unconcealer-cmd stop_session

Available tools:
  Session: start_session, stop_session, list_sessions
  Registers: read_registers
  Memory: read_memory, write_memory
  Execution: continue_execution, step, step_over, halt
  Breakpoints: set_breakpoint, delete_breakpoint
  Analysis: backtrace, evaluate, read_fault_registers, read_exception_frame,
            check_interrupt_priorities, analyze_crash
""",
    )

    parser.add_argument(
        "--session", "-s",
        default="default",
        help="Session name (default: 'default')"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text"
    )
    parser.add_argument(
        "tool",
        help="Tool to execute"
    )
    parser.add_argument(
        "args",
        nargs="*",
        help="Tool arguments (positional or --key=value)"
    )

    # Tool-specific arguments
    parser.add_argument("--machine", default="lm3s6965evb", help="QEMU machine type")
    parser.add_argument("--cpu", default="cortex-m3", help="CPU type")
    parser.add_argument("--address", help="Memory address")
    parser.add_argument("--length", type=int, default=64, help="Memory length")
    parser.add_argument("--data", help="Hex data to write")
    parser.add_argument("--location", help="Breakpoint location")
    parser.add_argument("--condition", help="Breakpoint condition")
    parser.add_argument("--temporary", action="store_true", help="Temporary breakpoint")
    parser.add_argument("--number", type=int, help="Breakpoint number")
    parser.add_argument("--expression", help="Expression to evaluate")
    parser.add_argument("--max-frames", type=int, default=20, help="Max backtrace frames")
    parser.add_argument("--instruction", action="store_true", help="Step by instruction")
    parser.add_argument("--stack-pointer", help="Stack pointer for exception frame")
    parser.add_argument("--registers", nargs="*", help="Register names to read")

    return parser.parse_args()


def build_tool_args(parsed_args, positional: List[str]) -> Dict[str, Any]:
    """Build tool arguments from parsed args and positional args."""
    tool = parsed_args.tool
    args: Dict[str, Any] = {}

    # Handle positional arguments based on tool
    if tool == "start_session" and positional:
        args["elf_path"] = positional[0]
    elif tool == "read_memory" and positional:
        args["address"] = positional[0]
        if len(positional) > 1:
            args["length"] = int(positional[1])
    elif tool == "write_memory" and positional:
        args["address"] = positional[0]
        if len(positional) > 1:
            args["data"] = positional[1]
    elif tool == "set_breakpoint" and positional:
        args["location"] = positional[0]
    elif tool == "delete_breakpoint" and positional:
        args["number"] = int(positional[0])
    elif tool == "evaluate" and positional:
        args["expression"] = " ".join(positional)

    # Add named arguments
    if parsed_args.machine:
        args["machine"] = parsed_args.machine
    if parsed_args.cpu:
        args["cpu"] = parsed_args.cpu
    if parsed_args.address:
        args["address"] = parsed_args.address
    if parsed_args.length:
        args["length"] = parsed_args.length
    if parsed_args.data:
        args["data"] = parsed_args.data
    if parsed_args.location:
        args["location"] = parsed_args.location
    if parsed_args.condition:
        args["condition"] = parsed_args.condition
    if parsed_args.temporary:
        args["temporary"] = True
    if parsed_args.number:
        args["number"] = parsed_args.number
    if parsed_args.expression:
        args["expression"] = parsed_args.expression
    if parsed_args.max_frames:
        args["max_frames"] = parsed_args.max_frames
    if parsed_args.instruction:
        args["instruction"] = True
    if parsed_args.stack_pointer:
        args["stack_pointer"] = parsed_args.stack_pointer
    if parsed_args.registers:
        args["registers"] = parsed_args.registers

    return args


def main():
    """Main entry point."""
    parsed = parse_args()
    tool_args = build_tool_args(parsed, parsed.args)

    # Run the tool
    result = asyncio.run(execute_tool(parsed.tool, tool_args, parsed.session))

    # Output
    if parsed.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_output(result))

    # Exit with error code if error
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
