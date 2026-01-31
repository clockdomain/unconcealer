# QEMU Controller Implementation

This document describes the implementation of the QEMU Controller component in unconcealer.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌──────────────┐
│   Unconcealer   │────▶│ QEMUController  │────▶│     QEMU     │
│   (Python)      │     │  (async)        │     │   Process    │
└─────────────────┘     └────────┬────────┘     └──────┬───────┘
                                 │                      │
                                 │ QMP Socket           │ GDB Server
                                 │ (Port 4444)          │ (Port 1234)
                                 ▼                      ▼
                        ┌────────────────┐     ┌──────────────┐
                        │  QMP Protocol  │     │  GDB Bridge  │
                        │  (JSON-RPC)    │     │  (pygdbmi)   │
                        └────────────────┘     └──────────────┘
```

### Components

1. **QEMUController** (`src/unconcealer/tools/qemu_control.py`)
   - Manages QEMU subprocess lifecycle
   - Connects to QMP for VM control
   - Provides pause/resume/snapshot functionality

2. **QMP (QEMU Machine Protocol)**
   - JSON-based protocol for machine control
   - Runs on TCP socket (default port 4444)
   - Allows VM management without GDB

3. **GDB Server**
   - Built into QEMU (`-gdb tcp::1234`)
   - Used by GDBBridge for debugging
   - Separate from QMP control channel

## QMP Protocol

QEMU Machine Protocol is a JSON-based protocol for controlling QEMU instances.

### Message Format

**Request:**
```json
{"execute": "command-name", "arguments": {"arg1": "value1"}}
```

**Response (success):**
```json
{"return": {...}}
```

**Response (error):**
```json
{"error": {"class": "GenericError", "desc": "..."}}
```

### Key Commands

| Command | Description |
|---------|-------------|
| `qmp_capabilities` | Negotiate QMP capabilities (required first) |
| `stop` | Pause VM execution |
| `cont` | Resume VM execution |
| `system_reset` | Reset the VM |
| `quit` | Terminate QEMU |
| `query-status` | Get VM status |
| `query-cpus-fast` | Get CPU information |
| `human-monitor-command` | Execute HMP command (for snapshots) |

## Implementation Details

### Class Structure

```python
@dataclass
class QEMUConfig:
    qemu_path: str = "qemu-system-arm"
    machine: str = "lm3s6965evb"      # Cortex-M3 board
    cpu: str = "cortex-m3"
    memory: str = "64K"
    gdb_port: int = 1234
    qmp_port: int = 4444
    extra_args: List[str] = field(default_factory=list)

class QEMUController:
    config: QEMUConfig
    process: Optional[subprocess.Popen[bytes]]
    qmp_socket: Optional[socket.socket]
    _running: bool
```

### Method Categories

#### Lifecycle
- `start(elf_path, wait_for_gdb)` - Start QEMU with firmware
- `stop()` - Terminate QEMU gracefully

#### Execution Control
- `pause()` - Pause VM
- `resume()` - Resume VM
- `reset()` - Reset VM

#### Snapshots
- `save_snapshot(name)` - Save VM state
- `load_snapshot(name)` - Restore VM state
- `delete_snapshot(name)` - Delete snapshot

#### Status
- `query_status()` - Get VM running state
- `query_cpus()` - Get CPU information

## QEMU Command Line

The controller builds a command like:

```bash
qemu-system-arm \
    -machine lm3s6965evb \
    -cpu cortex-m3 \
    -m 64K \
    -kernel firmware.elf \
    -gdb tcp::1234 \
    -qmp tcp:localhost:4444,server,wait=off \
    -nographic \
    -S  # Start paused (if wait_for_gdb=True)
```

### Key Flags

| Flag | Purpose |
|------|---------|
| `-machine` | Board/SoC model |
| `-cpu` | CPU model |
| `-kernel` | ELF firmware to load |
| `-gdb tcp::1234` | Enable GDB server |
| `-qmp tcp:...,server,wait=off` | Enable QMP, don't wait for client |
| `-nographic` | No GUI, use serial console |
| `-S` | Start paused, wait for debugger |

## Lessons Learned

### 1. QMP Connection Timing

QEMU needs time to start before QMP is available:

```python
async def start(self, elf_path: str) -> bool:
    self.process = subprocess.Popen(cmd, ...)
    await asyncio.sleep(0.5)  # Wait for QMP
    await self._connect_qmp()
```

### 2. QMP Capabilities Negotiation

Must send `qmp_capabilities` before other commands:

```python
async def _connect_qmp(self) -> None:
    # Read greeting
    greeting = await self._qmp_recv()

    # Must negotiate capabilities first
    await self._qmp_send({"execute": "qmp_capabilities"})
    await self._qmp_recv()
```

### 3. Non-blocking Socket with asyncio

Use `setblocking(False)` and `loop.sock_recv()`:

```python
self.qmp_socket.setblocking(False)

async def _qmp_recv(self) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    chunk = await loop.sock_recv(self.qmp_socket, 4096)
```

### 4. Graceful Shutdown

Try QMP quit first, then terminate:

```python
async def stop(self) -> None:
    if self.qmp_socket:
        try:
            await self.qmp_execute("quit")
        except Exception:
            pass
        self.qmp_socket.close()

    if self.process:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except TimeoutExpired:
            self.process.kill()
```

### 5. Snapshot Limitations

Snapshots require a block device with snapshot support. For simple ELF loading (no disk image), snapshots may not work:

```python
# Uses HMP command (human monitor protocol) for snapshots
result = await self.qmp_execute(
    "human-monitor-command",
    {"command-line": f"savevm {name}"}
)
```

## Usage Example

```python
import asyncio
from unconcealer.tools import QEMUController, QEMUConfig

async def debug_firmware():
    config = QEMUConfig(
        machine="lm3s6965evb",
        cpu="cortex-m3",
        gdb_port=1234,
    )

    qemu = QEMUController(config)

    try:
        # Start QEMU with firmware
        await qemu.start('firmware.elf')

        # Check status (should be paused due to -S)
        status = await qemu.query_status()
        print(f"VM status: {status}")

        # Now GDB can connect on port 1234
        # ... use GDBBridge ...

        # Control via QMP
        await qemu.resume()
        await asyncio.sleep(1)
        await qemu.pause()

    finally:
        await qemu.stop()

asyncio.run(debug_firmware())
```

## Testing

### Unit Tests (no QEMU required)

```bash
pytest tests/test_qemu_control.py -v -m "not integration"
```

Tests use mocked subprocess and socket to verify:
- Configuration handling
- Command building
- QMP message formatting
- State management

### Integration Tests (requires QEMU)

```bash
# Run tests that actually start QEMU
pytest tests/test_qemu_control.py -v -m integration
```

Integration tests verify:
- QEMU starts and stops cleanly
- QMP connection works
- Pause/resume functionality
- CPU query works

## References

- [QEMU QMP Protocol](https://www.qemu.org/docs/master/interop/qmp-intro.html)
- [QMP Commands Reference](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html)
- [QEMU GDB Usage](https://www.qemu.org/docs/master/system/gdb.html)
- [LM3S6965 Board](https://www.qemu.org/docs/master/system/arm/stellaris.html)
