# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unconcealer is an AI-powered embedded systems debugger that uses QEMU and GDB to debug firmware. It provides both a CLI for interactive debugging with LLM assistance and an MCP server for Claude Desktop integration.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run unit tests (no hardware/QEMU required)
pytest tests/ -v

# Run a single test
pytest tests/test_session.py::test_function_name -v

# Integration tests (requires QEMU running)
pytest -m integration -v

# Linting and type checking
ruff check src/
mypy src/ --ignore-missing-imports

# CLI usage
unconcealer doctor                           # Verify dependencies
unconcealer shell firmware.elf               # Headless interactive debug (no LLM)
unconcealer debug firmware.elf               # Interactive debug with LLM
unconcealer mcp-server                       # Start MCP server for Claude Desktop
unconcealer analyze firmware.elf --fault hardfault

# Single-command interface (for Claude Code)
unconcealer-cmd start_session firmware.elf   # Start QEMU + GDB session
unconcealer-cmd read_registers               # Read CPU registers
unconcealer-cmd set_breakpoint main          # Set breakpoint
unconcealer-cmd continue_execution           # Run until breakpoint/fault
unconcealer-cmd analyze_crash                # Full crash analysis
unconcealer-cmd stop_session                 # Stop and cleanup
```

### Test Firmware (for integration tests)

```bash
cd test_fw
rustup target add thumbv7m-none-eabi
cargo build --release

# Start QEMU with GDB stub
qemu-system-arm -M lm3s6965evb \
    -kernel target/thumbv7m-none-eabi/release/test_fw \
    -S -gdb tcp::1234 -nographic
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLI (cli.py) / MCP Server                    │
│                 Entry points for user interaction               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────────────┐
│ AgentOrchest- │   │ SessionManager│   │ TargetArchitecture    │
│ rator         │   │ (MCP)         │   │ (arch/)               │
│ - LLM queries │   │ - Multi-sess  │   │ - CortexM, RISC-V     │
│ - Findings    │   │ - Lifecycle   │   │ - Fault decoding      │
└───────┬───────┘   └───────┬───────┘   └───────────────────────┘
        │                   │
        └─────────┬─────────┘
                  ▼
        ┌─────────────────┐
        │   DebugSession  │  ← Unified debugging interface
        │   (core/)       │
        └────────┬────────┘
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
┌──────────────┐    ┌──────────────┐
│QEMUController│    │  GDBBridge   │
│(tools/)      │    │  (tools/)    │
│- VM lifecycle│    │- Registers   │
│- Snapshots   │    │- Memory      │
│- Reset       │    │- Breakpoints │
└──────────────┘    └──────────────┘
```

### Key Components

- **DebugSession** (`core/session.py`): Unified async interface combining QEMU and GDB. Use as async context manager.

- **GDBBridge** (`tools/gdb_bridge.py`): Wraps pygdbmi for GDB/MI protocol. Handles register reads, memory access, breakpoints, stepping.

- **QEMUController** (`tools/qemu_control.py`): Manages QEMU process lifecycle, QMP socket, snapshots. `QEMUConfig` dataclass for machine/cpu settings.

- **StdioMcpServer** (`mcp/stdio_server.py`): MCP JSON-RPC server over stdin/stdout. Tool definitions in `_build_tool_definitions()`.

- **SessionManager** (`mcp/session_manager.py`): Manages multiple debug sessions for MCP. Tracks current session and architecture handler.

- **TargetArchitecture** (`arch/base.py`): Abstract base for architecture support. Implementations provide fault register decoding, exception frame parsing, interrupt analysis.

### Supported Architectures

- **CortexM** (`arch/cortex_m.py`): ARM Cortex-M0/M3/M4/M7. Decodes CFSR, HFSR, MMFAR, BFAR fault registers. Parses exception stack frame.

- **RISC-V** (`arch/riscv.py`): 32/64-bit RISC-V. Handles mcause, mtval, mepc. Parses trap frame.

## Code Patterns

- All I/O is async (`async def`, `await`). Tests use `pytest-asyncio` with `asyncio_mode = "auto"`.

- Type annotations throughout. Run `mypy` to check.

- Dataclasses for structured types (`QEMUConfig`, `StopInfo`, `BreakpointInfo`, `FaultState`, etc.).

- MCP tools return `{"content": [{"type": "text", "text": "..."}]}` format via `_text_response()`.

## MCP Server Integration

Configure in Claude Desktop:
```json
{
  "mcpServers": {
    "embedded-debugger": {
      "command": "unconcealer",
      "args": ["mcp-server"]
    }
  }
}
```

Environment variables: `DEBUGGER_GDB_PATH`, `DEBUGGER_QEMU_ARM_PATH`, `DEBUGGER_LOG_FILE`, `DEBUGGER_LOG_LEVEL`.

## Claude Code Usage Guide

This section explains how Claude Code should help users debug embedded firmware with unconcealer.

### What Claude Code Can Do

**With `unconcealer-cmd` (RECOMMENDED - full autonomous debugging):**
- Start/stop debug sessions via Bash commands
- Read registers, memory, and fault state directly
- Set breakpoints and control execution
- Analyze crashes without user intervention
- No copy/paste workflow needed
- Works out of the box - no MCP configuration required

**With MCP configured (also full autonomous debugging):**
- Same capabilities as above, but via MCP protocol
- Requires MCP server configuration in settings

**By guiding the user (interactive shell fallback):**
- Explain what shell commands to run
- Interpret register values, memory dumps, and fault states
- Provide ARM Cortex-M / RISC-V debugging expertise
- Help form and test debugging hypotheses

### Verification First

Before debugging, verify the environment:

```bash
# Check all dependencies (QEMU, GDB, etc.) - Claude Code can run this
unconcealer doctor

# Quick integration test with firmware - Claude Code can run this
unconcealer test path/to/firmware.elf --quick
```

### Autonomous Debugging with `unconcealer-cmd` (RECOMMENDED)

Claude Code can directly control debugging sessions using `unconcealer-cmd`. This is the preferred method as it requires no user intervention.

**Starting a Session:**
```bash
# Start QEMU and connect GDB - session persists between commands
unconcealer-cmd start_session /path/to/firmware.elf

# With specific machine/CPU
unconcealer-cmd start_session firmware.elf --machine lm3s6965evb --cpu cortex-m3

# Named session (for multiple concurrent sessions)
unconcealer-cmd --session myfw start_session firmware.elf
```

**Debugging Commands:**
```bash
# Read all CPU registers
unconcealer-cmd read_registers

# Read specific registers
unconcealer-cmd read_registers --registers pc sp lr

# Read memory (hex dump format)
unconcealer-cmd read_memory 0x20000000 --length 64

# Set breakpoint and run
unconcealer-cmd set_breakpoint main
unconcealer-cmd continue_execution

# Single step
unconcealer-cmd step
unconcealer-cmd step --instruction  # assembly-level

# Get call stack
unconcealer-cmd backtrace

# Evaluate expression
unconcealer-cmd evaluate "sizeof(struct task)"
```

**Crash Analysis:**
```bash
# Read fault registers (CFSR, HFSR, etc.)
unconcealer-cmd read_fault_registers

# Full crash analysis (fault + exception frame + interrupts)
unconcealer-cmd analyze_crash

# Get exception frame
unconcealer-cmd read_exception_frame
```

**Session Management:**
```bash
# List active sessions
unconcealer-cmd list_sessions

# Stop session (kills QEMU)
unconcealer-cmd stop_session

# Work with named sessions
unconcealer-cmd --session fw1 start_session firmware1.elf
unconcealer-cmd --session fw2 start_session firmware2.elf
unconcealer-cmd --session fw1 read_registers
unconcealer-cmd --session fw2 read_registers
```

**JSON Output:**
```bash
# Get machine-readable JSON output
unconcealer-cmd analyze_crash --json
```

### Interactive Debug Sessions (User-Driven)

The `unconcealer shell` command starts an interactive session that **the user drives**. Claude Code should tell the user what commands to run and interpret the output they share.

```bash
# User runs this in their terminal
unconcealer shell firmware.elf

# With specific machine/CPU configuration
unconcealer shell firmware.elf --machine lm3s6965evb --cpu cortex-m3
```

Shell commands the user can run:
- `regs` / `registers` - Show CPU registers
- `mem <addr> [len]` - Read memory (e.g., `mem 0x20000000 64`)
- `write <addr> <bytes>` - Write memory (e.g., `write 0x20000000 01020304`)
- `break <location>` - Set breakpoint (e.g., `break main`, `break *0x800`)
- `delete <num>` - Delete breakpoint
- `continue` / `c` - Continue execution
- `step` / `s` - Single step
- `next` / `n` - Step over
- `halt` - Stop execution
- `bt` / `backtrace` - Show call stack
- `eval <expr>` - Evaluate C expression
- `snapshot save <name>` - Save VM state
- `snapshot load <name>` - Restore VM state
- `exit` / `quit` - Exit session

### Understanding Fault States

For Cortex-M targets, when a crash occurs, read these fault registers:

| Register | Address | Purpose |
|----------|---------|---------|
| CFSR | 0xE000ED28 | Combined Fault Status (UsageFault, BusFault, MemManage) |
| HFSR | 0xE000ED2C | HardFault Status |
| MMFAR | 0xE000ED34 | MemManage Fault Address |
| BFAR | 0xE000ED38 | BusFault Address |

CFSR bit meanings:
- Bits 0-7: MemManage faults (MMARVALID=bit 7, DACCVIOL=bit 1, IACCVIOL=bit 0)
- Bits 8-15: BusFault (BFARVALID=bit 15, PRECISERR=bit 9, IMPRECISERR=bit 10)
- Bits 16-25: UsageFault (DIVBYZERO=bit 25, UNALIGNED=bit 24, UNDEFINSTR=bit 16)

HFSR bit meanings:
- Bit 30 (FORCED): Fault escalated to HardFault
- Bit 1 (VECTTBL): Vector table read fault

### Common Debugging Workflow

Guide the user through these steps:

1. **Start session and check initial state:**
   - Tell user: "Run `unconcealer shell firmware.elf`"
   - Tell user: "Type `regs` to see registers, then `bt` for backtrace"
   - User shares output, Claude Code interprets

2. **Set breakpoint at entry point:**
   - Tell user: "Type `break main` then `continue`"
   - Wait for user to share where execution stopped

3. **Examine state when stopped:**
   - Tell user: "Run `regs` and `bt`"
   - Tell user: "Run `mem 0x20000000 32` to read RAM"
   - Interpret the hex dump for them

4. **If crashed/faulted, read fault registers:**
   - Tell user: "Run `mem 0xE000ED28 4` for CFSR"
   - Tell user: "Run `mem 0xE000ED2C 4` for HFSR"
   - Decode the fault bits and explain what went wrong

5. **Use snapshots for experimentation:**
   - Tell user: "Run `snapshot save before_crash`"
   - After crash: "Run `snapshot load before_crash` to go back"

### Interpreting Memory Output

Memory is displayed as hex bytes. For 32-bit values on little-endian ARM:
- `78 56 34 12` = 0x12345678
- `EF BE AD DE` = 0xDEADBEEF

### Typical Crash Analysis

When analyzing a crash:

1. Check PC value - is it in valid code space?
2. Check SP value - is stack pointer valid?
3. Check LR (link register) - where did we come from?
4. Read CFSR/HFSR to identify fault type
5. If BFARVALID or MMARVALID set, read corresponding address register
6. Get backtrace to see call chain

Example interpretation:
- CFSR = 0x00000400 → PRECISERR (bit 9) = precise BusFault
- HFSR = 0x40000000 → FORCED (bit 30) = escalated to HardFault
- BFAR = 0xFFFFFFFF → Attempted access to invalid address

### What Claude Code Cannot Do

- **Cannot drive interactive REPL sessions** - `unconcealer shell` requires human input
- **Cannot see real-time streaming output** - must use command-based workflow

### Recommended Workflow with Claude Code

**Primary method (autonomous):**
1. User asks for help debugging firmware
2. Claude Code runs `unconcealer doctor` to verify setup
3. Claude Code uses `unconcealer-cmd` to start session and debug autonomously:
   ```bash
   unconcealer-cmd start_session /path/to/firmware.elf
   unconcealer-cmd set_breakpoint main
   unconcealer-cmd continue_execution
   unconcealer-cmd analyze_crash
   ```
4. Claude Code interprets results and continues debugging
5. No user intervention needed until issue is found

**Fallback method (manual):**
If `unconcealer-cmd` is unavailable, fall back to guiding the user through `unconcealer shell`.

### For Fully AI-Driven Debugging

Two options are available:
1. **`unconcealer-cmd`** (recommended) - Works via Bash, no configuration needed
2. **MCP server** - Works via MCP protocol, requires configuration

### Using MCP with Claude Code

Claude Code can connect to MCP servers, giving it direct access to debugging tools without user intermediation.

**Configuration:**

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "embedded-debugger": {
      "command": "/full/path/to/unconcealer/.venv/bin/unconcealer",
      "args": ["mcp-server"]
    }
  }
}
```

**Important:** Use the full path to the unconcealer executable in the venv, since Claude Code won't have shell PATH access.

**Available MCP Tools:**

Once configured, Claude Code can directly call these tools:

| Tool | Description |
|------|-------------|
| `start_session` | Start QEMU + GDB session with ELF file |
| `stop_session` | Stop session and cleanup |
| `read_registers` | Read CPU registers |
| `read_memory` | Read memory at address or symbol |
| `write_memory` | Write bytes to memory |
| `continue_execution` | Run until breakpoint/fault |
| `step` / `step_over` | Single-step execution |
| `halt` / `reset` | Stop or reset target |
| `set_breakpoint` | Set breakpoint at function/address |
| `delete_breakpoint` | Remove breakpoint |
| `backtrace` | Get call stack |
| `evaluate` | Evaluate C expression |
| `read_fault_registers` | Read and decode fault state |
| `read_exception_frame` | Parse stacked exception frame |
| `check_interrupt_priorities` | Check NVIC/PLIC config |
| `analyze_crash` | Comprehensive crash analysis |
| `save_snapshot` / `load_snapshot` | VM state management |

**Example Workflow with MCP:**

When MCP is configured, Claude Code can autonomously:
1. Call `start_session` with the ELF path
2. Call `set_breakpoint` at main
3. Call `continue_execution` and get stop reason
4. Call `read_registers` and `backtrace` to examine state
5. If crashed, call `analyze_crash` for full diagnosis
6. Call `stop_session` when done

This eliminates the copy/paste workflow - Claude Code drives debugging directly.

### Using MCP with Claude Desktop

Add to Claude Desktop config (`~/.config/Claude/claude_desktop_config.json` on Linux):

```json
{
  "mcpServers": {
    "embedded-debugger": {
      "command": "/full/path/to/unconcealer/.venv/bin/unconcealer",
      "args": ["mcp-server"]
    }
  }
}
```

### Helping Users Debug

**Using `unconcealer-cmd` (RECOMMENDED):**

1. Run `unconcealer doctor` to verify setup
2. Ask for the ELF file path
3. Start session and debug autonomously:
   ```bash
   unconcealer-cmd start_session /path/to/firmware.elf
   unconcealer-cmd set_breakpoint main
   unconcealer-cmd continue_execution
   unconcealer-cmd read_registers
   unconcealer-cmd backtrace
   unconcealer-cmd analyze_crash
   unconcealer-cmd stop_session
   ```
4. Interpret results and iterate until issue is found

**Using MCP (alternative):**

Same workflow as above, but via MCP protocol if configured.

**Using interactive shell (fallback):**

If `unconcealer-cmd` is unavailable:
1. Tell user to start `unconcealer shell <elf>` in their terminal
2. Guide them through shell commands, ask them to paste output
3. Interpret register values, memory dumps, and fault states
4. Form hypotheses and tell them what to run next

### Architecture-Specific Notes

**Cortex-M:**
- PC bit 0 is always 1 (Thumb mode indicator)
- Exception return uses special LR values (0xFFFFFFF1, 0xFFFFFFF9, 0xFFFFFFFD)
- Vector table at 0x00000000 (or VTOR offset)
- Stack must be 8-byte aligned on exception entry

**RISC-V:**
- mcause register indicates trap cause (interrupt vs exception)
- mepc holds faulting instruction address
- mtval may contain additional fault info (address, instruction)
