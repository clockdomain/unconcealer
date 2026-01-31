# GDB Bridge Implementation

This document describes the implementation of the GDB Bridge component in unconcealer.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────┐     ┌──────────────┐     ┌──────────┐
│   Unconcealer   │────▶│  GDBBridge  │────▶│    pygdbmi   │────▶│   GDB    │
│   (Python)      │     │  (async)    │     │  (GDB/MI)    │     │ Process  │
└─────────────────┘     └─────────────┘     └──────────────┘     └────┬─────┘
                                                                      │
                                                                      │ GDB Remote
                                                                      │ Protocol
                                                                      ▼
                                                                ┌──────────┐
                                                                │   QEMU   │
                                                                │ gdbstub  │
                                                                └──────────┘
```

### Components

1. **GDBBridge** (`src/unconcealer/tools/gdb_bridge.py`)
   - High-level async Python interface
   - Wraps pygdbmi's GdbController
   - Parses GDB/MI responses into Python objects

2. **pygdbmi** (third-party library)
   - Manages GDB subprocess
   - Sends commands via stdin
   - Parses GDB/MI output format

3. **GDB** (GNU Debugger)
   - Runs in MI (Machine Interface) mode
   - Connects to QEMU's gdbstub via remote protocol
   - Use `gdb-multiarch` for cross-architecture support

4. **QEMU gdbstub**
   - Built into QEMU (`-gdb tcp::1234`)
   - Implements GDB remote serial protocol
   - Provides access to CPU state, memory, breakpoints

## GDB/MI Protocol

GDB's Machine Interface (MI) is a line-based protocol designed for IDE integration.

### Command Format

```
-command-name arg1 arg2 ...
```

Examples:
```
-target-select remote localhost:1234
-file-exec-and-symbols /path/to/firmware.elf
-data-read-memory-bytes 0x20000000 16
-exec-continue
```

### Response Format

Responses are JSON-like records:

```
^done,value="42"                    # Synchronous result
*stopped,reason="breakpoint-hit"    # Async notification
~"Hello\n"                          # Console output
&"warning: ...\n"                   # Log output
```

pygdbmi parses these into Python dicts:
```python
{
    "type": "result",
    "message": "done",
    "payload": {"value": "42"}
}
```

### Key Messages

| Message | Meaning |
|---------|---------|
| `done` | Command completed successfully |
| `connected` | Remote target connected |
| `running` | Execution started |
| `stopped` | Execution stopped (breakpoint, signal, etc.) |
| `error` | Command failed |

## Implementation Details

### Class Structure

```python
class GDBBridge:
    gdb_path: str              # Path to GDB executable
    gdb: GdbController         # pygdbmi controller
    connected: bool            # Connection state
    _breakpoints: Dict[int, BreakpointInfo]  # Active breakpoints
```

### Data Classes

```python
@dataclass
class StopInfo:
    reason: StopReason         # Why execution stopped
    address: int               # PC value
    signal_name: Optional[str] # Signal if applicable

@dataclass
class BreakpointInfo:
    number: int                # GDB breakpoint ID
    address: int               # Address
    enabled: bool              # Active state
    location: str              # Original location string
```

### Method Categories

#### Lifecycle
- `start()` - Launch GDB process
- `connect(host, port)` - Connect to remote target
- `load_symbols(elf_path)` - Load debug symbols
- `close()` - Terminate GDB

#### Execution Control
- `continue_execution()` - Resume until stop
- `halt()` - Interrupt execution
- `step(instruction=False)` - Single step
- `step_over(instruction=False)` - Step over calls
- `finish()` - Run until function returns

#### Register/Memory Access
- `read_registers(names)` - Read CPU registers
- `read_register(name)` - Read single register
- `read_memory(address, length)` - Read memory bytes
- `write_memory(address, data)` - Write memory bytes
- `read_memory_word(address)` - Read 32-bit word

#### Breakpoints
- `set_breakpoint(location, condition, temporary)`
- `delete_breakpoint(number)`
- `enable_breakpoint(number)`
- `disable_breakpoint(number)`

#### Analysis
- `evaluate(expression)` - Evaluate C expression
- `get_backtrace(max_frames)` - Get stack trace

## Lessons Learned

### 1. Timeout Handling

pygdbmi defaults to 1-second timeouts, which is too short for:
- Loading large symbol files
- Connecting to remote targets
- Operations on slow targets

**Solution:** Use 10-second default timeout:
```python
def _write(self, command: str, timeout_sec: int = 10):
    return self.gdb.write(command, timeout_sec=timeout_sec)
```

### 2. Response Message Types

The `connect` command returns `"connected"` not `"done"`:

```python
def _check_success(self, response):
    for r in response:
        # Must check for multiple success indicators
        if r.get("message") in ("done", "connected", "running"):
            return True
```

### 3. Value Parsing

GDB annotates values with symbol information:
```
0x452 <test_fw::__cortex_m_rt_main+22>
```

**Solution:** Strip annotations before parsing:
```python
def _parse_int(self, value: str) -> int:
    if " " in value:
        value = value.split()[0]  # Take only hex part
    return int(value, 16)
```

### 4. GDB Selection

`arm-none-eabi-gdb` may have missing dependencies. Use `gdb-multiarch` instead:
```python
gdb = GDBBridge(gdb_path='gdb-multiarch')
```

## Usage Example

```python
import asyncio
from unconcealer.tools import GDBBridge

async def debug_firmware():
    async with GDBBridge(gdb_path='gdb-multiarch') as gdb:
        # Load symbols and connect
        await gdb.load_symbols('firmware.elf')
        await gdb.connect('localhost', 1234)

        # Read initial state
        regs = await gdb.read_registers(['pc', 'sp', 'lr'])
        print(f"PC: 0x{regs['pc']:08x}")

        # Set breakpoint and run
        bp = await gdb.set_breakpoint('main')
        stop = await gdb.continue_execution()

        if stop.reason == StopReason.BREAKPOINT:
            print(f"Hit breakpoint at 0x{stop.address:08x}")

            # Read memory
            data = await gdb.read_memory(0x20000000, 16)
            print(f"RAM: {data.hex()}")

asyncio.run(debug_firmware())
```

## Testing

### Unit Tests (no QEMU required)

```bash
pytest tests/test_gdb_bridge.py -v
```

Tests use mocked GdbController to verify:
- Response parsing
- Command generation
- State management

### Integration Tests (requires QEMU)

1. Start QEMU with gdbstub:
```bash
qemu-system-arm -M lm3s6965evb \
    -kernel test_fw/target/thumbv7m-none-eabi/release/test_fw \
    -S -gdb tcp::1234 -nographic
```

2. Run integration test:
```bash
pytest tests/test_gdb_bridge.py -v -m integration
```

## References

- [GDB/MI Protocol](https://sourceware.org/gdb/current/onlinedocs/gdb.html/GDB_002fMI.html)
- [pygdbmi Documentation](https://github.com/cs01/pygdbmi)
- [QEMU GDB Usage](https://www.qemu.org/docs/master/system/gdb.html)
- [GDB Remote Protocol](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Remote-Protocol.html)
