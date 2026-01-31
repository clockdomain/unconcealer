"""Debug session combining QEMU and GDB."""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

from unconcealer.tools.gdb_bridge import (
    GDBBridge,
    StopInfo,
    BreakpointInfo,
)
from unconcealer.tools.qemu_control import QEMUController, QEMUConfig


@dataclass
class DebugSession:
    """Combined QEMU + GDB debug session.

    Provides a unified interface for debugging embedded firmware by
    managing both QEMU (emulation) and GDB (debugging) together.

    Example:
        async with DebugSession(elf_path="firmware.elf") as session:
            regs = await session.read_registers(["pc", "sp"])
            print(f"PC: 0x{regs['pc']:08x}")

            await session.set_breakpoint("main")
            await session.continue_execution()
    """

    elf_path: str
    qemu_config: QEMUConfig = field(default_factory=QEMUConfig)
    gdb_path: str = "gdb-multiarch"

    # Internal state (not init params)
    qemu: Optional[QEMUController] = field(default=None, init=False)
    gdb: Optional[GDBBridge] = field(default=None, init=False)
    _started: bool = field(default=False, init=False)

    # === Lifecycle ===

    async def start(self) -> bool:
        """Start debug session.

        Starts QEMU with the firmware and connects GDB.

        Returns:
            True if session started successfully

        Raises:
            RuntimeError: If QEMU or GDB fails to start
        """
        # Start QEMU
        self.qemu = QEMUController(self.qemu_config)
        await self.qemu.start(self.elf_path)

        # Connect GDB
        self.gdb = GDBBridge(self.gdb_path)
        await self.gdb.start()
        await self.gdb.load_symbols(self.elf_path)
        await self.gdb.connect(port=self.qemu_config.gdb_port)

        self._started = True
        return True

    async def stop(self) -> None:
        """Stop debug session.

        Closes GDB connection and stops QEMU.
        """
        if self.gdb:
            try:
                await self.gdb.close()
            except Exception:
                pass
            self.gdb = None

        if self.qemu:
            try:
                await self.qemu.stop()
            except Exception:
                pass
            self.qemu = None

        self._started = False

    @property
    def started(self) -> bool:
        """Check if session is started."""
        return self._started

    # === Execution Control ===

    async def continue_execution(self) -> StopInfo:
        """Continue execution until stop event.

        Returns:
            StopInfo describing why execution stopped
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.continue_execution()

    async def step(self, instruction: bool = False) -> StopInfo:
        """Single step execution.

        Args:
            instruction: If True, step one instruction; else step one source line

        Returns:
            StopInfo describing where we stopped
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.step(instruction=instruction)

    async def step_over(self, instruction: bool = False) -> StopInfo:
        """Step over function calls.

        Args:
            instruction: If True, step one instruction; else step one source line

        Returns:
            StopInfo describing where we stopped
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.step_over(instruction=instruction)

    async def halt(self) -> None:
        """Halt execution."""
        self._ensure_started()
        assert self.gdb is not None
        await self.gdb.halt()

    # === Register Operations ===

    async def read_registers(
        self, registers: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """Read CPU registers.

        Args:
            registers: List of register names, or None for all

        Returns:
            Dict mapping register name to value
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.read_registers(registers)

    async def read_register(self, name: str) -> int:
        """Read a single register.

        Args:
            name: Register name (e.g., "pc", "sp", "r0")

        Returns:
            Register value
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.read_register(name)

    # === Memory Operations ===

    async def read_memory(self, address: int, length: int) -> bytes:
        """Read memory bytes.

        Args:
            address: Start address
            length: Number of bytes to read

        Returns:
            Memory contents as bytes
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.read_memory(address, length)

    async def write_memory(self, address: int, data: bytes) -> bool:
        """Write memory bytes.

        Args:
            address: Start address
            data: Bytes to write

        Returns:
            True if write succeeded
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.write_memory(address, data)

    async def read_memory_word(self, address: int) -> int:
        """Read a 32-bit word from memory.

        Args:
            address: Address (should be 4-byte aligned)

        Returns:
            32-bit value (little-endian)
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.read_memory_word(address)

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
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.set_breakpoint(location, condition, temporary)

    async def delete_breakpoint(self, number: int) -> bool:
        """Delete a breakpoint.

        Args:
            number: Breakpoint number

        Returns:
            True if deleted successfully
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.delete_breakpoint(number)

    # === Analysis ===

    async def evaluate(self, expression: str) -> str:
        """Evaluate a C expression.

        Args:
            expression: C expression to evaluate

        Returns:
            Result as string
        """
        self._ensure_started()
        assert self.gdb is not None
        result = await self.gdb.evaluate(expression)
        return result.value

    async def get_backtrace(self, max_frames: int = 20) -> List[Dict[str, Any]]:
        """Get stack backtrace.

        Args:
            max_frames: Maximum number of frames

        Returns:
            List of frame dicts with addr, func, file, line
        """
        self._ensure_started()
        assert self.gdb is not None
        return await self.gdb.get_backtrace(max_frames)

    # === Snapshots (via QEMU) ===

    async def save_snapshot(self, name: str) -> bool:
        """Save VM snapshot.

        Note: Requires QEMU snapshot support (may not work with simple ELF loading).

        Args:
            name: Snapshot name

        Returns:
            True if saved successfully
        """
        self._ensure_started()
        assert self.qemu is not None
        return await self.qemu.save_snapshot(name)

    async def load_snapshot(self, name: str) -> bool:
        """Load VM snapshot.

        Args:
            name: Snapshot name

        Returns:
            True if loaded successfully
        """
        self._ensure_started()
        assert self.qemu is not None
        return await self.qemu.load_snapshot(name)

    # === VM Control (via QEMU) ===

    async def reset(self) -> bool:
        """Reset the VM.

        Returns:
            True if reset successfully
        """
        self._ensure_started()
        assert self.qemu is not None
        return await self.qemu.reset()

    # === Internal ===

    def _ensure_started(self) -> None:
        """Ensure session is started."""
        if not self._started:
            raise RuntimeError("Debug session not started")

    # === Context Manager ===

    async def __aenter__(self) -> "DebugSession":
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        await self.stop()
