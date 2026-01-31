"""QEMU Controller for managing QEMU instances via QMP."""

import subprocess
import socket
import json
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, cast


@dataclass
class QEMUConfig:
    """QEMU configuration.

    Attributes:
        qemu_path: Path to QEMU executable
        machine: Machine type (default: lm3s6965evb for Cortex-M3)
        cpu: CPU type (default: cortex-m3)
        memory: Memory size
        gdb_port: GDB server port
        qmp_port: QMP control port
        extra_args: Additional QEMU arguments
    """
    qemu_path: str = "qemu-system-arm"
    machine: str = "lm3s6965evb"
    cpu: str = "cortex-m3"
    memory: str = "64K"
    gdb_port: int = 1234
    qmp_port: int = 4444
    extra_args: List[str] = field(default_factory=list)


class QEMUController:
    """Controls QEMU instance via QMP (QEMU Machine Protocol).

    Provides async interface for starting/stopping QEMU, controlling execution,
    and managing VM snapshots. Designed for embedded firmware debugging.

    Example:
        async with QEMUController() as qemu:
            await qemu.start('firmware.elf')
            await qemu.pause()
            await qemu.save_snapshot('initial')
            await qemu.resume()
    """

    def __init__(self, config: Optional[QEMUConfig] = None) -> None:
        """Initialize QEMU controller.

        Args:
            config: QEMU configuration (uses defaults if not provided)
        """
        self.config = config or QEMUConfig()
        self.process: Optional[subprocess.Popen[bytes]] = None
        self.qmp_socket: Optional[socket.socket] = None
        self._running = False
        self._elf_path: Optional[str] = None

    # === Lifecycle Methods ===

    async def start(self, elf_path: str, wait_for_gdb: bool = True) -> bool:
        """Start QEMU with firmware.

        Args:
            elf_path: Path to ELF firmware binary
            wait_for_gdb: If True, start paused waiting for GDB (-S flag)

        Returns:
            True if started successfully

        Raises:
            RuntimeError: If QEMU fails to start or QMP connection fails
        """
        self._elf_path = elf_path

        cmd = [
            self.config.qemu_path,
            "-machine", self.config.machine,
            "-cpu", self.config.cpu,
            "-m", self.config.memory,
            "-kernel", elf_path,
            "-gdb", f"tcp::{self.config.gdb_port}",
            "-qmp", f"tcp:localhost:{self.config.qmp_port},server,wait=off",
            "-nographic",
        ]

        if wait_for_gdb:
            cmd.append("-S")  # Start paused

        cmd.extend(self.config.extra_args)

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"QEMU not found at '{self.config.qemu_path}'\n"
                f"Try: --qemu-arm-path /path/to/qemu-system-arm\n"
                f"Or install: sudo apt install qemu-system-arm"
            )
        except PermissionError:
            raise RuntimeError(
                f"Permission denied running QEMU at '{self.config.qemu_path}'\n"
                f"Check that the file is executable: chmod +x {self.config.qemu_path}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start QEMU: {e}")

        # Wait for QMP to be ready
        await asyncio.sleep(0.5)

        # Check if process is still running
        if self.process.poll() is not None:
            stderr = self.process.stderr.read().decode() if self.process.stderr else ""
            raise RuntimeError(f"QEMU exited immediately: {stderr}")

        try:
            await self._connect_qmp()
            self._running = True
            return True
        except Exception as e:
            await self.stop()
            raise RuntimeError(f"Failed to connect QMP: {e}")

    async def stop(self) -> None:
        """Stop QEMU instance."""
        # Try graceful shutdown via QMP
        if self.qmp_socket:
            try:
                await self.qmp_execute("quit")
            except Exception:
                pass
            try:
                self.qmp_socket.close()
            except Exception:
                pass
            self.qmp_socket = None

        # Terminate process
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None

        self._running = False

    # === QMP Connection ===

    async def _connect_qmp(self, timeout: float = 5.0) -> None:
        """Connect to QMP socket.

        Args:
            timeout: Connection timeout in seconds

        Raises:
            ConnectionError: If connection fails
        """
        self.qmp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.qmp_socket.settimeout(timeout)

        try:
            self.qmp_socket.connect(("localhost", self.config.qmp_port))
        except socket.error as e:
            raise ConnectionError(f"Failed to connect to QMP: {e}")

        self.qmp_socket.setblocking(False)

        # Read greeting
        greeting = await self._qmp_recv()
        if "QMP" not in greeting:
            raise ConnectionError(f"Invalid QMP greeting: {greeting}")

        # Send capabilities negotiation
        await self._qmp_send({"execute": "qmp_capabilities"})
        response = await self._qmp_recv()
        if "return" not in response:
            raise ConnectionError(f"QMP capabilities failed: {response}")

    async def _qmp_send(self, msg: Dict[str, Any]) -> None:
        """Send QMP message.

        Args:
            msg: Message dict to send
        """
        if not self.qmp_socket:
            raise RuntimeError("QMP not connected")
        data = json.dumps(msg).encode() + b"\n"
        self.qmp_socket.send(data)

    async def _qmp_recv(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Receive QMP response.

        Args:
            timeout: Read timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            TimeoutError: If read times out
        """
        if not self.qmp_socket:
            raise RuntimeError("QMP not connected")

        loop = asyncio.get_event_loop()
        data = b""
        deadline = asyncio.get_event_loop().time() + timeout

        while True:
            try:
                chunk = await asyncio.wait_for(
                    loop.sock_recv(self.qmp_socket, 4096),
                    timeout=max(0.1, deadline - loop.time())
                )
                if not chunk:
                    raise ConnectionError("QMP connection closed")
                data += chunk
                if b"\n" in data:
                    break
            except asyncio.TimeoutError:
                if loop.time() >= deadline:
                    raise TimeoutError("QMP receive timeout")
            except BlockingIOError:
                await asyncio.sleep(0.01)

        return cast(Dict[str, Any], json.loads(data.decode()))

    async def qmp_execute(
        self,
        command: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """Execute QMP command.

        Args:
            command: QMP command name
            arguments: Optional command arguments
            timeout: Response timeout

        Returns:
            QMP response dict
        """
        msg: Dict[str, Any] = {"execute": command}
        if arguments:
            msg["arguments"] = arguments
        await self._qmp_send(msg)
        return await self._qmp_recv(timeout=timeout)

    # === Execution Control ===

    async def pause(self) -> bool:
        """Pause VM execution.

        Returns:
            True if paused successfully
        """
        response = await self.qmp_execute("stop")
        # stop returns {"return": {}} on success, or an event
        return "return" in response or "event" in response

    async def resume(self) -> bool:
        """Resume VM execution.

        Returns:
            True if resumed successfully
        """
        response = await self.qmp_execute("cont")
        # cont returns {"event": "RESUME"} on success
        return "return" in response or "event" in response

    async def reset(self) -> bool:
        """Reset the VM.

        Returns:
            True if reset successfully
        """
        response = await self.qmp_execute("system_reset")
        return "return" in response

    # === Snapshots ===

    async def save_snapshot(self, name: str) -> bool:
        """Save VM snapshot.

        Note: Snapshots require a block device with snapshot support.
        For simple ELF loading, this may not be available.

        Args:
            name: Snapshot name

        Returns:
            True if saved successfully
        """
        result = await self.qmp_execute(
            "human-monitor-command",
            {"command-line": f"savevm {name}"}
        )
        return "error" not in result

    async def load_snapshot(self, name: str) -> bool:
        """Load VM snapshot.

        Args:
            name: Snapshot name

        Returns:
            True if loaded successfully
        """
        result = await self.qmp_execute(
            "human-monitor-command",
            {"command-line": f"loadvm {name}"}
        )
        return "error" not in result

    async def delete_snapshot(self, name: str) -> bool:
        """Delete VM snapshot.

        Args:
            name: Snapshot name

        Returns:
            True if deleted successfully
        """
        result = await self.qmp_execute(
            "human-monitor-command",
            {"command-line": f"delvm {name}"}
        )
        return "error" not in result

    # === Status ===

    async def query_status(self) -> Dict[str, Any]:
        """Query VM status.

        Returns:
            Status dict with 'running' and 'status' keys
        """
        response = await self.qmp_execute("query-status")
        result = response.get("return", {})
        return cast(Dict[str, Any], result)

    async def query_cpus(self) -> List[Dict[str, Any]]:
        """Query CPU information.

        Returns:
            List of CPU info dicts
        """
        response = await self.qmp_execute("query-cpus-fast")
        result = response.get("return", [])
        return cast(List[Dict[str, Any]], result)

    @property
    def running(self) -> bool:
        """Check if QEMU is running."""
        return self._running

    @property
    def gdb_port(self) -> int:
        """Get the GDB port."""
        return self.config.gdb_port

    @property
    def elf_path(self) -> Optional[str]:
        """Get the loaded ELF path."""
        return self._elf_path

    # === Context Manager ===

    async def __aenter__(self) -> "QEMUController":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()
