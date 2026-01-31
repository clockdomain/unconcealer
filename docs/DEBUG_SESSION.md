# Debug Session Implementation

This document describes the DebugSession component that unifies QEMU and GDB for embedded debugging.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     DebugSession                            │
│  ┌─────────────────────┐    ┌─────────────────────┐        │
│  │   QEMUController    │    │     GDBBridge       │        │
│  │   - Start/Stop      │    │   - Execution       │        │
│  │   - Snapshots       │    │   - Registers       │        │
│  │   - Reset           │    │   - Memory          │        │
│  └──────────┬──────────┘    └──────────┬──────────┘        │
│             │                          │                    │
└─────────────┼──────────────────────────┼────────────────────┘
              │                          │
              │ QMP                       │ GDB/MI
              │ (Port 4444)              │ (Port 1234)
              ▼                          ▼
         ┌─────────────────────────────────────┐
         │               QEMU                   │
         │  - ARM Cortex-M3 emulation          │
         │  - Firmware execution               │
         │  - GDB server                       │
         └─────────────────────────────────────┘
```

## Purpose

The `DebugSession` class provides a unified interface for debugging embedded firmware by:

1. **Managing Lifecycle**: Starting/stopping both QEMU and GDB together
2. **Simplifying Access**: Single API for all debugging operations
3. **Coordinating State**: Ensuring QEMU and GDB stay synchronized
4. **Resource Cleanup**: Proper shutdown on errors or completion

## Class Structure

```python
@dataclass
class DebugSession:
    # Configuration (init params)
    elf_path: str                    # Path to firmware ELF
    qemu_config: QEMUConfig          # QEMU settings
    gdb_path: str                    # Path to GDB executable

    # Internal state
    qemu: Optional[QEMUController]   # QEMU controller instance
    gdb: Optional[GDBBridge]         # GDB bridge instance
    _started: bool                   # Session state
```

## Method Categories

### Lifecycle
| Method | Description |
|--------|-------------|
| `start()` | Start QEMU and connect GDB |
| `stop()` | Close GDB and stop QEMU |
| `started` | Property: check if session running |

### Execution Control (via GDB)
| Method | Description |
|--------|-------------|
| `continue_execution()` | Run until breakpoint/signal |
| `step(instruction)` | Single step (line or instruction) |
| `step_over(instruction)` | Step over function calls |
| `halt()` | Interrupt execution |

### Registers (via GDB)
| Method | Description |
|--------|-------------|
| `read_registers(names)` | Read multiple registers |
| `read_register(name)` | Read single register |

### Memory (via GDB)
| Method | Description |
|--------|-------------|
| `read_memory(addr, len)` | Read memory bytes |
| `write_memory(addr, data)` | Write memory bytes |
| `read_memory_word(addr)` | Read 32-bit word |

### Breakpoints (via GDB)
| Method | Description |
|--------|-------------|
| `set_breakpoint(location)` | Set breakpoint |
| `delete_breakpoint(number)` | Delete breakpoint |

### Analysis (via GDB)
| Method | Description |
|--------|-------------|
| `evaluate(expression)` | Evaluate C expression |
| `get_backtrace(max_frames)` | Get stack trace |

### VM Control (via QEMU)
| Method | Description |
|--------|-------------|
| `save_snapshot(name)` | Save VM state |
| `load_snapshot(name)` | Restore VM state |
| `reset()` | Reset VM |

## Usage Examples

### Basic Usage

```python
import asyncio
from unconcealer.core import DebugSession

async def debug_firmware():
    session = DebugSession(elf_path="firmware.elf")

    try:
        await session.start()

        # Read registers
        regs = await session.read_registers(["pc", "sp", "lr"])
        print(f"PC: 0x{regs['pc']:08x}")
        print(f"SP: 0x{regs['sp']:08x}")

        # Set breakpoint and run
        bp = await session.set_breakpoint("main")
        stop = await session.continue_execution()
        print(f"Stopped at 0x{stop.address:08x}")

        # Read memory
        data = await session.read_memory(0x20000000, 16)
        print(f"RAM: {data.hex()}")

    finally:
        await session.stop()

asyncio.run(debug_firmware())
```

### Using Context Manager

```python
async def debug_firmware():
    async with DebugSession(elf_path="firmware.elf") as session:
        # Session automatically started

        regs = await session.read_registers(["pc"])
        print(f"PC: 0x{regs['pc']:08x}")

        # Session automatically stopped on exit
```

### Custom Configuration

```python
from unconcealer.tools import QEMUConfig

config = QEMUConfig(
    machine="lm3s6965evb",
    cpu="cortex-m3",
    gdb_port=5678,
    qmp_port=9999,
)

async with DebugSession(
    elf_path="firmware.elf",
    qemu_config=config,
    gdb_path="/usr/bin/gdb-multiarch",
) as session:
    # Debug with custom configuration
    pass
```

### Crash Investigation

```python
async def investigate_crash():
    async with DebugSession(elf_path="firmware.elf") as session:
        # Run until crash
        stop = await session.continue_execution()

        if stop.reason == StopReason.SIGNAL:
            print(f"Crashed with signal: {stop.signal_name}")

            # Get backtrace
            bt = await session.get_backtrace(10)
            print("Backtrace:")
            for frame in bt:
                print(f"  {frame['func']} at 0x{frame['addr']:08x}")

            # Read key registers
            regs = await session.read_registers(["pc", "sp", "lr", "r0"])
            for name, value in regs.items():
                print(f"  {name}: 0x{value:08x}")
```

## Startup Sequence

When `start()` is called:

1. **Create QEMUController** with configuration
2. **Start QEMU** with firmware ELF (`-S` flag pauses at start)
3. **Create GDBBridge** with GDB path
4. **Start GDB** process
5. **Load symbols** from ELF file
6. **Connect GDB** to QEMU's GDB server
7. **Mark session as started**

```
         DebugSession.start()
                │
                ▼
    ┌───────────────────────┐
    │ QEMUController.start() │
    │   - Launch QEMU       │
    │   - Wait for QMP      │
    │   - Connect QMP       │
    └───────────┬───────────┘
                │
                ▼
    ┌───────────────────────┐
    │   GDBBridge.start()   │
    │   - Launch GDB        │
    │   - Load symbols      │
    │   - Connect to QEMU   │
    └───────────┬───────────┘
                │
                ▼
         Session Ready
```

## Error Handling

The session handles errors gracefully:

```python
async def stop(self) -> None:
    """Stop debug session."""
    if self.gdb:
        try:
            await self.gdb.close()
        except Exception:
            pass  # Continue cleanup
        self.gdb = None

    if self.qemu:
        try:
            await self.qemu.stop()
        except Exception:
            pass  # Continue cleanup
        self.qemu = None

    self._started = False
```

Operations check session state:

```python
def _ensure_started(self) -> None:
    """Ensure session is started."""
    if not self._started:
        raise RuntimeError("Debug session not started")
```

## Testing

### Unit Tests (no QEMU required)

```bash
pytest tests/test_session.py -v -m "not integration"
```

21 unit tests verify:
- Configuration handling
- Lifecycle management
- Method delegation to GDB/QEMU
- Error handling
- Context manager behavior

### Integration Tests (requires QEMU)

```bash
pytest tests/test_session.py -v -m integration
```

3 integration tests verify:
- Full session start/stop
- Register reading
- Backtrace retrieval

## Future Enhancements

The DebugSession forms the foundation for:

1. **Agent Integration** (Week 3 Task 3.2-3.5)
   - Tool definitions for Claude Agent SDK
   - AgentOrchestrator wrapping DebugSession

2. **Snapshot Management** (Week 4)
   - Named checkpoint system
   - Automatic state persistence

3. **Enhanced Analysis** (Phase 2)
   - Memory inspection with formatting
   - Register interpretation
   - Fault analysis

## References

- [GDB_BRIDGE.md](GDB_BRIDGE.md) - GDB Bridge implementation details
- [QEMU_CONTROL.md](QEMU_CONTROL.md) - QEMU Controller implementation details
