"""GDB Machine Interface bridge for communicating with GDB."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any
from pygdbmi.gdbcontroller import GdbController


class StopReason(Enum):
    """Reasons why execution stopped."""
    BREAKPOINT = "breakpoint-hit"
    WATCHPOINT = "watchpoint-trigger"
    SIGNAL = "signal"
    STEP = "end-stepping-range"
    EXITED = "exited"
    EXITED_NORMALLY = "exited-normally"


@dataclass
class StopInfo:
    """Information about why execution stopped."""
    reason: StopReason
    address: int
    signal_name: Optional[str] = None
    breakpoint_number: Optional[int] = None


@dataclass
class BreakpointInfo:
    """Information about a breakpoint."""
    number: int
    address: int
    enabled: bool
    location: str
    hits: int = 0


@dataclass
class EvalResult:
    """Result of expression evaluation."""
    value: str
    type: Optional[str] = None


class GDBBridge:
    """GDB Machine Interface bridge.

    Provides async interface for controlling GDB via the MI protocol.
    Designed to connect to QEMU's gdbstub for embedded debugging.
    """

    def __init__(self, gdb_path: str = "arm-none-eabi-gdb") -> None:
        """Initialize GDB bridge.

        Args:
            gdb_path: Path to GDB executable (default: arm-none-eabi-gdb)
        """
        self.gdb_path = gdb_path
        self.gdb: Optional[GdbController] = None
        self.connected = False
        self._breakpoints: Dict[int, BreakpointInfo] = {}

    # === Lifecycle Methods ===

    async def start(self) -> None:
        """Start GDB process."""
        self.gdb = GdbController([self.gdb_path, "--interpreter=mi3"])

    async def connect(self, host: str = "localhost", port: int = 1234) -> bool:
        """Connect to remote target (e.g., QEMU gdbstub).

        Args:
            host: Target host
            port: GDB port (QEMU default: 1234)

        Returns:
            True if connected successfully
        """
        if not self.gdb:
            await self.start()
        response = self._write(f"-target-select remote {host}:{port}")
        self.connected = self._check_success(response)
        return self.connected

    async def load_symbols(self, elf_path: str) -> bool:
        """Load symbols from ELF file.

        Args:
            elf_path: Path to ELF binary

        Returns:
            True if symbols loaded successfully
        """
        response = self._write(f"-file-exec-and-symbols {elf_path}")
        return self._check_success(response)

    async def close(self) -> None:
        """Close GDB connection and exit."""
        if self.gdb:
            try:
                self.gdb.exit()
            except Exception:
                pass
            self.gdb = None
        self.connected = False
        self._breakpoints.clear()

    # === Execution Control ===

    async def continue_execution(self) -> StopInfo:
        """Continue execution until stop event.

        Returns:
            StopInfo describing why execution stopped
        """
        response = self._write("-exec-continue")
        return self._parse_stop(response)

    async def halt(self) -> None:
        """Halt execution (send interrupt)."""
        self._write("-exec-interrupt")

    async def step(self, instruction: bool = False) -> StopInfo:
        """Single step execution.

        Args:
            instruction: If True, step one instruction; else step one source line

        Returns:
            StopInfo describing where we stopped
        """
        cmd = "-exec-step-instruction" if instruction else "-exec-step"
        response = self._write(cmd)
        return self._parse_stop(response)

    async def step_over(self, instruction: bool = False) -> StopInfo:
        """Step over function calls.

        Args:
            instruction: If True, step one instruction; else step one source line

        Returns:
            StopInfo describing where we stopped
        """
        cmd = "-exec-next-instruction" if instruction else "-exec-next"
        response = self._write(cmd)
        return self._parse_stop(response)

    async def finish(self) -> StopInfo:
        """Execute until current function returns.

        Returns:
            StopInfo describing where we stopped
        """
        response = self._write("-exec-finish")
        return self._parse_stop(response)

    # === Register Operations ===

    async def read_registers(self, registers: Optional[List[str]] = None) -> Dict[str, int]:
        """Read CPU registers.

        Args:
            registers: List of register names to read, or None for all

        Returns:
            Dict mapping register name to value
        """
        if registers:
            result = {}
            for reg in registers:
                response = self._write(f"-data-evaluate-expression ${reg}")
                value = self._parse_eval_result(response)
                if value:
                    result[reg] = self._parse_int(value.value)
            return result
        else:
            response = self._write("-data-list-register-values x")
            return self._parse_register_values(response)

    async def read_register(self, name: str) -> int:
        """Read a single register.

        Args:
            name: Register name (without $)

        Returns:
            Register value
        """
        regs = await self.read_registers([name])
        return regs.get(name, 0)

    # === Memory Operations ===

    async def read_memory(self, address: int, length: int) -> bytes:
        """Read raw memory bytes.

        Args:
            address: Start address
            length: Number of bytes to read

        Returns:
            Memory contents as bytes
        """
        response = self._write(f"-data-read-memory-bytes 0x{address:x} {length}")
        return self._parse_memory_bytes(response)

    async def write_memory(self, address: int, data: bytes) -> bool:
        """Write to memory.

        Args:
            address: Start address
            data: Bytes to write

        Returns:
            True if write succeeded
        """
        hex_data = data.hex()
        response = self._write(f"-data-write-memory-bytes 0x{address:x} {hex_data}")
        return self._check_success(response)

    async def read_memory_word(self, address: int) -> int:
        """Read a 32-bit word from memory.

        Args:
            address: Address (should be 4-byte aligned)

        Returns:
            32-bit value (little-endian)
        """
        data = await self.read_memory(address, 4)
        return int.from_bytes(data, byteorder='little')

    # === Breakpoints ===

    async def set_breakpoint(
        self,
        location: str,
        condition: Optional[str] = None,
        temporary: bool = False,
    ) -> BreakpointInfo:
        """Set a breakpoint.

        Args:
            location: Function name, file:line, or *address
            condition: Optional condition expression
            temporary: If True, breakpoint is deleted after first hit

        Returns:
            BreakpointInfo for the created breakpoint
        """
        cmd = "-break-insert"
        if temporary:
            cmd += " -t"
        if condition:
            cmd += f' -c "{condition}"'
        cmd += f" {location}"

        response = self._write(cmd)
        bp = self._parse_breakpoint(response)
        if bp is None:
            raise RuntimeError(f"Failed to set breakpoint at {location}")
        self._breakpoints[bp.number] = bp
        return bp

    async def delete_breakpoint(self, number: int) -> bool:
        """Delete a breakpoint.

        Args:
            number: Breakpoint number

        Returns:
            True if deleted successfully
        """
        response = self._write(f"-break-delete {number}")
        if self._check_success(response):
            self._breakpoints.pop(number, None)
            return True
        return False

    async def disable_breakpoint(self, number: int) -> bool:
        """Disable a breakpoint."""
        response = self._write(f"-break-disable {number}")
        return self._check_success(response)

    async def enable_breakpoint(self, number: int) -> bool:
        """Enable a breakpoint."""
        response = self._write(f"-break-enable {number}")
        return self._check_success(response)

    # === Expression Evaluation ===

    async def evaluate(self, expression: str) -> EvalResult:
        """Evaluate an expression.

        Args:
            expression: C expression to evaluate

        Returns:
            EvalResult with the value
        """
        response = self._write(f'-data-evaluate-expression "{expression}"')
        result = self._parse_eval_result(response)
        return result or EvalResult(value="<error>")

    # === Stack Operations ===

    async def get_backtrace(self, max_frames: int = 20) -> List[Dict[str, Any]]:
        """Get stack backtrace.

        Args:
            max_frames: Maximum number of frames to return

        Returns:
            List of frame dictionaries with addr, func, file, line
        """
        response = self._write(f"-stack-list-frames 0 {max_frames - 1}")
        return self._parse_backtrace(response)

    # === Internal Methods ===

    def _write(self, command: str, timeout_sec: int = 10) -> List[Dict[str, Any]]:
        """Send command to GDB and return response."""
        if not self.gdb:
            raise RuntimeError("GDB not started")
        return self.gdb.write(command, timeout_sec=timeout_sec)

    def _check_success(self, response: List[Dict[str, Any]]) -> bool:
        """Check if GDB response indicates success."""
        for r in response:
            if r.get("message") in ("done", "connected", "running"):
                return True
            if r.get("message") == "error":
                return False
        return False

    def _parse_stop(self, response: List[Dict[str, Any]]) -> StopInfo:
        """Parse stop response from execution commands."""
        for r in response:
            if r.get("message") == "stopped":
                payload = r.get("payload", {})
                reason_str = payload.get("reason", "unknown")
                try:
                    reason = StopReason(reason_str)
                except ValueError:
                    reason = StopReason.SIGNAL

                frame = payload.get("frame", {})
                addr_str = frame.get("addr", "0")

                return StopInfo(
                    reason=reason,
                    address=self._parse_int(addr_str),
                    signal_name=payload.get("signal-name"),
                    breakpoint_number=payload.get("bkptno"),
                )
        return StopInfo(reason=StopReason.SIGNAL, address=0)

    def _parse_int(self, value: str) -> int:
        """Parse integer from GDB response (handles 0x prefix and annotations)."""
        if not value:
            return 0
        value = value.strip()
        # Handle values like "0x452 <test_fw::__cortex_m_rt_main+22>"
        if " " in value:
            value = value.split()[0]
        if value.startswith("0x") or value.startswith("0X"):
            return int(value, 16)
        return int(value)

    def _parse_memory_bytes(self, response: List[Dict[str, Any]]) -> bytes:
        """Parse memory read response."""
        for r in response:
            if r.get("message") == "done":
                payload = r.get("payload", {})
                memory = payload.get("memory", [])
                if memory:
                    contents = memory[0].get("contents", "")
                    return bytes.fromhex(contents)
        return b""

    def _parse_register_values(self, response: List[Dict[str, Any]]) -> Dict[str, int]:
        """Parse register values response."""
        result = {}
        for r in response:
            if r.get("message") == "done":
                payload = r.get("payload", {})
                for reg in payload.get("register-values", []):
                    num = reg.get("number", "")
                    val = reg.get("value", "0")
                    result[f"r{num}"] = self._parse_int(val)
        return result

    def _parse_eval_result(self, response: List[Dict[str, Any]]) -> Optional[EvalResult]:
        """Parse expression evaluation response."""
        for r in response:
            if r.get("message") == "done":
                payload = r.get("payload", {})
                value = payload.get("value", "")
                return EvalResult(value=value)
        return None

    def _parse_breakpoint(self, response: List[Dict[str, Any]]) -> Optional[BreakpointInfo]:
        """Parse breakpoint creation response."""
        for r in response:
            if r.get("message") == "done":
                payload = r.get("payload", {})
                bkpt = payload.get("bkpt", {})
                if bkpt:
                    return BreakpointInfo(
                        number=int(bkpt.get("number", 0)),
                        address=self._parse_int(bkpt.get("addr", "0")),
                        enabled=bkpt.get("enabled") == "y",
                        location=bkpt.get("original-location", ""),
                    )
        return None

    def _parse_backtrace(self, response: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse backtrace response."""
        frames = []
        for r in response:
            if r.get("message") == "done":
                payload = r.get("payload", {})
                stack = payload.get("stack", [])
                for frame in stack:
                    f = frame.get("frame", frame)
                    frames.append({
                        "level": int(f.get("level", 0)),
                        "addr": self._parse_int(f.get("addr", "0")),
                        "func": f.get("func", "??"),
                        "file": f.get("file"),
                        "line": int(f.get("line", 0)) if f.get("line") else None,
                    })
        return frames

    # === Context Manager ===

    async def __aenter__(self) -> "GDBBridge":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
