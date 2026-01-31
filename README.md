# Unconcealer

AI-powered embedded systems debugger using Claude and QEMU/GDB.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   AgentOrchestrator                     │
│  - Manages Claude conversation                          │
│  - Tracks session memory (snapshots, findings)          │
│  - Provides MCP tools to Claude                         │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│                    DebugSession                         │
│  - Unified interface for debugging                      │
│  - Coordinates QEMU and GDB                             │
└───────────┬─────────────────────────────┬───────────────┘
            │                             │
┌───────────▼───────────┐     ┌───────────▼───────────────┐
│    QEMUController     │     │        GDBBridge          │
│  - VM lifecycle       │     │  - Register/memory access │
│  - Snapshots          │     │  - Breakpoints, stepping  │
│  - Reset/halt         │     │  - Symbol resolution      │
└───────────────────────┘     └───────────────────────────┘
```

## Installation

### From GitHub

```bash
pip install git+https://github.com/clockdomain/unconcealer.git
```

### From source

```bash
git clone https://github.com/clockdomain/unconcealer.git
cd unconcealer
pip install -e .
```

## Usage

```bash
unconcealer debug firmware.elf --target cortex-m4
unconcealer analyze firmware.elf --fault hardfault
unconcealer version
```

### Python API

```python
from unconcealer import DebugSession, AgentOrchestrator

async def debug_firmware():
    async with DebugSession(elf_path="firmware.elf") as session:
        orchestrator = AgentOrchestrator(session)

        # Ask Claude to investigate
        response = await orchestrator.query(
            "What caused the HardFault? Check the fault registers."
        )
        print(response)

        # Stream responses
        async for chunk in orchestrator.query_stream("Analyze the stack"):
            print(chunk, end="")

        # Access findings
        for finding in orchestrator.findings:
            print(f"[{finding.severity}] {finding.description}")
```

### Available Debug Tools

Claude has access to these tools during a debug session:

| Tool | Description |
|------|-------------|
| `read_registers` | Read CPU registers (pc, sp, lr, r0-r12) |
| `read_memory` | Read memory at address or symbol |
| `write_memory` | Write bytes to memory |
| `continue_execution` | Continue until breakpoint/exception |
| `step` / `step_over` | Single-step execution |
| `halt` / `reset` | Stop or reset the target |
| `set_breakpoint` | Set breakpoint at function/address |
| `delete_breakpoint` | Remove a breakpoint |
| `backtrace` | Get call stack |
| `evaluate` | Evaluate C expression |
| `save_snapshot` | Save VM state |
| `load_snapshot` | Restore VM state |

## Development

```bash
git clone https://github.com/clockdomain/unconcealer.git
cd unconcealer
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Testing

### Unit tests (no hardware required)

```bash
pytest tests/ -v
```

### Integration tests (requires QEMU)

1. Build the test firmware:
```bash
cd test_fw
cargo build --release
```

2. Start QEMU with gdbstub:
```bash
qemu-system-arm -M lm3s6965evb \
    -kernel test_fw/target/thumbv7m-none-eabi/release/test_fw \
    -S -gdb tcp::1234 -nographic
```

3. Run integration tests (in another terminal):
```bash
source venv/bin/activate
pytest -m integration -v
```

### All tests

```bash
# Unit tests only (default)
pytest tests/ -v

# Integration tests only
pytest -m integration -v

# All tests (requires QEMU running)
pytest tests/ -v --run-integration
```

### Linting and type checking

```bash
ruff check src/
mypy src/ --ignore-missing-imports
```
