# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Minimal Cortex-M3 test firmware for the Unconcealer debugger. Runs on QEMU's `lm3s6965evb` machine to validate GDB bridge functionality without real hardware.

## Build Commands

```bash
# Prerequisites
rustup target add thumbv7m-none-eabi

# Build (from test_fw directory)
cargo build --release

# Output: target/thumbv7m-none-eabi/release/test_fw
```

## Running with QEMU

```bash
# Start QEMU with GDB stub (halted, waiting for debugger)
qemu-system-arm -M lm3s6965evb \
    -kernel target/thumbv7m-none-eabi/release/test_fw \
    -S -gdb tcp::1234 -nographic

# Or use the configured runner
cargo run --release
```

## Architecture

```
test_fw/
├── src/main.rs          # Entry point, main loop, test functions
├── memory.x             # Linker script (LM3S6965: 256K FLASH, 64K RAM)
├── .cargo/config.toml   # Build config (target, linker flags, QEMU runner)
└── Cargo.toml           # Dependencies: cortex-m, cortex-m-rt, panic-halt
```

**Memory Layout:**
- FLASH: `0x00000000` (256K) - Code
- RAM: `0x20000000` (64K) - Data

**Key Symbols for Debugging:**
- `COUNTER` - Incremented each loop iteration
- `TEST_VALUE` - Initialized to `0x12345678`
- `test_function()` - Breakpoint target, returns COUNTER
- `trigger_hardfault()` - Triggers HardFault via invalid memory read

## Parent Project Integration

This firmware is used by the Python `unconcealer` debugger in the parent directory. See `/unconcealer/README.md` for:
- Python API usage
- Integration test setup
- Available debug tools (read_registers, read_memory, breakpoints, etc.)

## Testing

From the parent `unconcealer/` directory:

```bash
# Unit tests (no QEMU needed)
pytest tests/ -v

# Integration tests (requires QEMU running with this firmware)
pytest -m integration -v
```
