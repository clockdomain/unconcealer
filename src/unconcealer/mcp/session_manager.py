"""Session manager for multi-session MCP server.

Manages multiple debug sessions, allowing Claude Desktop to work
with multiple targets concurrently.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from unconcealer.core.session import DebugSession
from unconcealer.tools.qemu_control import QEMUConfig
from unconcealer.arch import detect_architecture, get_architecture, TargetArchitecture

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Information about a debug session."""

    name: str
    elf_path: str
    machine: str
    cpu: str
    gdb_port: int
    architecture: str = "cortex-m"
    created_at: datetime = field(default_factory=datetime.now)
    session: Optional[DebugSession] = None
    is_active: bool = False


class SessionManager:
    """Manages multiple debug sessions.

    The session manager tracks active debug sessions and provides
    a "current" session concept for tools that don't specify a target.

    Example:
        manager = SessionManager()

        # Start a session
        await manager.start_session(
            name="firmware1",
            elf_path="/path/to/firmware.elf",
            machine="lm3s6965evb",
            cpu="cortex-m3",
        )

        # Get current session
        session = manager.get_current_session()

        # Switch to different session
        manager.set_current("firmware2")

        # List all sessions
        for info in manager.list_sessions():
            print(f"{info.name}: {info.elf_path}")
    """

    def __init__(
        self,
        gdb_path: Optional[str] = None,
        qemu_arm_path: Optional[str] = None,
        qemu_riscv32_path: Optional[str] = None,
        qemu_riscv64_path: Optional[str] = None,
        snapshot_dir: Optional[str] = None,
    ):
        """Initialize session manager.

        Args:
            gdb_path: Path to GDB executable
            qemu_arm_path: Path to qemu-system-arm
            qemu_riscv32_path: Path to qemu-system-riscv32
            qemu_riscv64_path: Path to qemu-system-riscv64
            snapshot_dir: Directory for snapshot storage
        """
        self._sessions: Dict[str, SessionInfo] = {}
        self._current_name: Optional[str] = None
        self._next_port = 1234
        self._lock = asyncio.Lock()

        # Configuration from environment or parameters
        self.gdb_path = gdb_path or os.environ.get(
            "DEBUGGER_GDB_PATH", "gdb-multiarch"
        )
        self.qemu_paths = {
            "arm": qemu_arm_path
            or os.environ.get("DEBUGGER_QEMU_ARM_PATH", "qemu-system-arm"),
            "riscv32": qemu_riscv32_path
            or os.environ.get("DEBUGGER_QEMU_RISCV32_PATH", "qemu-system-riscv32"),
            "riscv64": qemu_riscv64_path
            or os.environ.get("DEBUGGER_QEMU_RISCV64_PATH", "qemu-system-riscv64"),
        }
        self.snapshot_dir = Path(
            snapshot_dir
            or os.environ.get("DEBUGGER_SNAPSHOT_DIR", "/tmp/unconcealer")
        )
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _get_qemu_path(self, machine: str, cpu: str) -> str:
        """Get QEMU executable path based on target."""
        cpu_lower = cpu.lower()
        machine_lower = machine.lower()

        if "rv64" in cpu_lower or "riscv64" in machine_lower:
            return self.qemu_paths["riscv64"]
        elif "rv32" in cpu_lower or "riscv32" in machine_lower or "sifive" in machine_lower:
            return self.qemu_paths["riscv32"]
        else:
            return self.qemu_paths["arm"]

    def _allocate_port(self) -> int:
        """Allocate a unique GDB port."""
        port = self._next_port
        self._next_port += 1
        return port

    async def start_session(
        self,
        elf_path: str,
        machine: str = "lm3s6965evb",
        cpu: str = "cortex-m3",
        name: Optional[str] = None,
        gdb_port: Optional[int] = None,
    ) -> SessionInfo:
        """Start a new debug session.

        Args:
            elf_path: Path to ELF binary
            machine: QEMU machine type
            cpu: CPU type
            name: Session name (auto-generated if not specified)
            gdb_port: GDB port (auto-allocated if not specified)

        Returns:
            SessionInfo with session details

        Raises:
            FileNotFoundError: If ELF file doesn't exist
            RuntimeError: If session start fails
        """
        async with self._lock:
            # Validate ELF exists
            elf = Path(elf_path).expanduser().resolve()
            if not elf.exists():
                raise FileNotFoundError(f"ELF file not found: {elf}")

            # Generate name if needed
            if name is None:
                name = elf.stem
                # Ensure unique name
                base_name = name
                counter = 1
                while name in self._sessions:
                    name = f"{base_name}_{counter}"
                    counter += 1

            if name in self._sessions:
                raise ValueError(f"Session '{name}' already exists")

            # Allocate port
            port = gdb_port or self._allocate_port()

            # Create QEMU config
            qemu_path = self._get_qemu_path(machine, cpu)
            config = QEMUConfig(
                machine=machine,
                cpu=cpu,
                gdb_port=port,
                qemu_path=qemu_path,
            )

            # Create and start session
            session = DebugSession(
                elf_path=str(elf),
                qemu_config=config,
                gdb_path=self.gdb_path,
            )

            try:
                await session.start()
            except Exception as e:
                logger.error(f"Failed to start session '{name}': {e}")
                raise RuntimeError(f"Failed to start session: {e}")

            # Detect architecture
            arch_name = detect_architecture(cpu, machine)

            # Register session
            info = SessionInfo(
                name=name,
                elf_path=str(elf),
                machine=machine,
                cpu=cpu,
                gdb_port=port,
                architecture=arch_name,
                session=session,
                is_active=True,
            )
            self._sessions[name] = info

            # Set as current if first session
            if self._current_name is None:
                self._current_name = name

            logger.info(f"Started session '{name}' for {elf}")
            return info

    async def stop_session(self, name: str) -> bool:
        """Stop a debug session.

        Args:
            name: Session name

        Returns:
            True if session was stopped
        """
        async with self._lock:
            if name not in self._sessions:
                return False

            info = self._sessions[name]
            if info.session:
                try:
                    await info.session.stop()
                except Exception as e:
                    logger.warning(f"Error stopping session '{name}': {e}")

            del self._sessions[name]

            # Update current if needed
            if self._current_name == name:
                self._current_name = (
                    next(iter(self._sessions.keys())) if self._sessions else None
                )

            logger.info(f"Stopped session '{name}'")
            return True

    async def stop_all(self) -> None:
        """Stop all sessions."""
        names = list(self._sessions.keys())
        for name in names:
            await self.stop_session(name)

    def get_session(self, name: str) -> Optional[DebugSession]:
        """Get a session by name.

        Args:
            name: Session name

        Returns:
            DebugSession or None
        """
        info = self._sessions.get(name)
        return info.session if info else None

    def get_current_session(self) -> Optional[DebugSession]:
        """Get the current session.

        Returns:
            Current DebugSession or None
        """
        if self._current_name:
            return self.get_session(self._current_name)
        return None

    def get_current_name(self) -> Optional[str]:
        """Get current session name."""
        return self._current_name

    def set_current(self, name: str) -> bool:
        """Set the current session.

        Args:
            name: Session name

        Returns:
            True if session exists and was set as current
        """
        if name in self._sessions:
            self._current_name = name
            return True
        return False

    def list_sessions(self) -> list[SessionInfo]:
        """List all sessions.

        Returns:
            List of SessionInfo objects
        """
        return list(self._sessions.values())

    def get_session_info(self, name: str) -> Optional[SessionInfo]:
        """Get session info by name.

        Args:
            name: Session name

        Returns:
            SessionInfo or None
        """
        return self._sessions.get(name)

    def get_architecture(self, name: Optional[str] = None) -> Optional[TargetArchitecture]:
        """Get architecture handler for a session.

        Args:
            name: Session name (uses current if not specified)

        Returns:
            TargetArchitecture instance or None
        """
        if name is None:
            name = self._current_name
        if name is None:
            return None

        info = self._sessions.get(name)
        if info is None:
            return None

        return get_architecture(info.architecture)

    def get_current_architecture(self) -> Optional[TargetArchitecture]:
        """Get architecture handler for current session.

        Returns:
            TargetArchitecture instance or None
        """
        return self.get_architecture(self._current_name)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session manager state.

        Returns:
            Dictionary with session information
        """
        return {
            "current": self._current_name,
            "sessions": [
                {
                    "name": info.name,
                    "elf_path": info.elf_path,
                    "machine": info.machine,
                    "cpu": info.cpu,
                    "gdb_port": info.gdb_port,
                    "architecture": info.architecture,
                    "created_at": info.created_at.isoformat(),
                    "is_active": info.is_active,
                }
                for info in self._sessions.values()
            ],
        }
