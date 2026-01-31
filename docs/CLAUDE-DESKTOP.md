# Unconcealer - AI-Powered Embedded Debugger
## Claude Desktop Integration Guide

**Version:** 2.0
**Date:** January 2026

---

## Quick Start Guide

This section gets you from zero to debugging in 10 minutes.

### Step 1: Install System Dependencies

```bash
# Ubuntu/Debian/WSL
sudo apt update
sudo apt install -y \
    qemu-system-arm \
    qemu-system-misc \
    gdb-multiarch \
    python3-pip \
    python3-venv \
    git

# macOS (with Homebrew)
brew install qemu python@3.11 git

# Verify QEMU and GDB are installed
qemu-system-arm --version
gdb-multiarch --version
```

### Step 2: Clone and Install Unconcealer

```bash
# Clone the repository
git clone https://github.com/anthropics/unconcealer.git
cd unconcealer

# Create and activate virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e .

# Verify installation
unconcealer --help
unconcealer mcp-server --help
```

### Step 3: Configure Claude Desktop

Find your Claude Desktop config file:

| OS | Location |
|----|----------|
| **Linux** | `~/.config/Claude/claude_desktop_config.json` |
| **macOS** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Windows** | `%APPDATA%\Claude\claude_desktop_config.json` |

Create or edit the file with:

```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "/path/to/unconcealer/.venv/bin/python",
      "args": ["-m", "unconcealer.cli", "mcp-server"],
      "env": {
        "DEBUGGER_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

> **Important:** Replace `/path/to/unconcealer` with your actual clone path.
>
> Example for Linux: `"/home/youruser/unconcealer/.venv/bin/python"`

**Restart Claude Desktop** (quit completely and reopen).

### Step 4: Test Drive with Sample Firmware

The repository includes a pre-built test firmware at:
```
test_fw/target/thumbv7m-none-eabi/release/test_fw
```

Open Claude Desktop and try:

```
You: I want to test the embedded debugger. Load the test firmware at
     /path/to/unconcealer/test_fw/target/thumbv7m-none-eabi/release/test_fw
     It's for Cortex-M3.
```

Claude will:
1. Start QEMU with the lm3s6965evb machine
2. Load the test firmware
3. Connect GDB

Then try these commands:

```
You: Show me the registers

You: Read memory at the COUNTER variable

You: Set a breakpoint at test_function and run

You: What's the value of COUNTER now?

You: Save a snapshot called "test1"

You: Continue running for a bit, then check COUNTER again

You: Go back to snapshot "test1" - what's COUNTER now?

You: Read the fault registers (there shouldn't be any faults)

You: Stop the session
```

### Step 5: Verify Everything Works

If all commands work, you're ready to debug your own firmware.

**Troubleshooting quick checks:**

```bash
# Is the MCP server starting?
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python -m unconcealer.cli mcp-server 2>/dev/null

# Expected: JSON response with "unconcealer" server info

# Is QEMU working?
qemu-system-arm -machine lm3s6965evb -nographic -kernel \
    test_fw/target/thumbv7m-none-eabi/release/test_fw &
# Should start without errors (kill with: pkill qemu-system-arm)
```

---

## Overview

This guide explains how to use the Agentic Embedded Debugger through **Claude Desktop** using the **Model Context Protocol (MCP)**. This is the recommended integration for most users because:

- **No API keys required** — uses your Claude Pro subscription
- **Natural conversation** — just chat, tools run automatically
- **Local execution** — QEMU and GDB run on your machine
- **Secure** — your firmware never leaves your computer

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   You: "My firmware crashes after 30 syscalls. Can you help?"              │
│                                                                             │
│   Claude Desktop                                                            │
│        │                                                                    │
│        │ (MCP Protocol - local connection)                                  │
│        ▼                                                                    │
│   ┌─────────────────┐                                                       │
│   │  MCP Server     │  ← Runs on your machine                              │
│   │  (debugger)     │                                                       │
│   └────────┬────────┘                                                       │
│            │                                                                │
│            ▼                                                                │
│   ┌─────────────────┐                                                       │
│   │  QEMU + GDB     │  ← Your firmware runs here                           │
│   │  (local)        │                                                       │
│   └─────────────────┘                                                       │
│                                                                             │
│   Claude: "I found the issue. PendSV priority is misconfigured..."         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Table of Contents

- [Quick Start Guide](#quick-start-guide) ← **Start here!**
1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Usage](#4-usage)
5. [Available Tools](#5-available-tools)
6. [Example Sessions](#6-example-sessions)
7. [Troubleshooting](#7-troubleshooting)
8. [Architecture](#8-architecture)
- [Appendix: Quick Reference](#appendix-quick-reference)
- [Appendix: Test Firmware](#appendix-test-firmware)

---

## 1. Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Claude Desktop | Latest | Chat interface with MCP support |
| Python | 3.10+ | Runs the debugger |
| QEMU | 7.0+ | Emulates your target |
| GDB | 12.0+ | Debug protocol |
| ARM Toolchain | Any | For ARM targets |

### Required Accounts

| Account | Cost | Purpose |
|---------|------|---------|
| Claude Pro | $20/month | Enables MCP and extended conversations |

**Note:** No Anthropic API key is required. Claude Desktop uses your subscription.

### Supported Targets

| Architecture | QEMU Machines |
|--------------|---------------|
| ARM Cortex-M0/M0+ | `lm3s6965evb` |
| ARM Cortex-M3 | `mps2-an385`, `lm3s6965evb` |
| ARM Cortex-M4 | `netduinoplus2` |
| ARM Cortex-M33 | `mps2-an505` |
| RISC-V | `sifive_e`, `virt` |

---

## 2. Installation

### Step 1: Install System Dependencies

```bash
# Ubuntu/Debian/WSL
sudo apt update
sudo apt install -y \
    qemu-system-arm \
    qemu-system-misc \
    gdb-multiarch \
    gcc-arm-none-eabi \
    python3-pip \
    python3-venv \
    git

# macOS (with Homebrew)
brew install qemu arm-none-eabi-gcc python@3.11

# Verify installation
qemu-system-arm --version
gdb-multiarch --version
```

### Step 2: Install from Git

```bash
# Clone the repository
git clone https://github.com/anthropics/unconcealer.git
cd unconcealer

# Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in development mode
pip install -e .
```

### Step 3: Verify Installation

```bash
# Check the debugger is installed
unconcealer --version

# Check MCP server starts
unconcealer mcp-server --help

# Quick protocol test
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python -m unconcealer.cli mcp-server 2>/dev/null
# Should output JSON with server info
```

---

## 3. Configuration

### Step 1: Locate Claude Desktop Config

| OS | Config File Location |
|----|---------------------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### Step 2: Add MCP Server Configuration

Edit (or create) the config file:

```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "/path/to/unconcealer/.venv/bin/python",
      "args": ["-m", "unconcealer.cli", "mcp-server"],
      "env": {
        "DEBUGGER_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

> **Important:** Replace `/path/to/unconcealer` with your actual installation path.
> Use the full path to the Python executable in your virtual environment.

**Alternative:** If you installed globally (not recommended):

```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "unconcealer",
      "args": ["mcp-server"]
    }
  }
}
```

### Step 3: Restart Claude Desktop

Close and reopen Claude Desktop completely. You should see "unconcealer" in the MCP servers list (click the 🔌 icon or hammer icon).

### Optional: Custom Configuration

For advanced setups with custom paths:

```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "/path/to/unconcealer/.venv/bin/python",
      "args": [
        "-m", "unconcealer.cli", "mcp-server",
        "--gdb-path", "/opt/arm-toolchain/bin/arm-none-eabi-gdb",
        "--qemu-arm-path", "/usr/local/bin/qemu-system-arm",
        "--qemu-riscv32-path", "/usr/local/bin/qemu-system-riscv32"
      ],
      "env": {
        "DEBUGGER_LOG_LEVEL": "DEBUG",
        "DEBUGGER_SNAPSHOT_DIR": "/tmp/unconcealer-snapshots"
      }
    }
  }
}
```

---

## 4. Usage

### Starting a Debug Session

Simply chat with Claude and mention your firmware:

```
You: I need to debug my firmware at ~/projects/robot/build/firmware.elf
     It's for an STM32F4 (Cortex-M4). Can you help me investigate a crash?
```

Claude will:
1. Start QEMU with appropriate settings
2. Load your firmware
3. Connect GDB
4. Begin investigation

### Basic Commands (Natural Language)

You don't need special syntax. Just describe what you want:

| You Say | Claude Does |
|---------|-------------|
| "Load my firmware at path/to/file.elf" | Starts QEMU, loads ELF |
| "Run until it crashes" | Sets up fault detection, continues |
| "What caused this crash?" | Reads fault registers, analyzes |
| "Show me the backtrace" | Gets stack trace with symbols |
| "What's in register R3?" | Reads specific register |
| "Set a breakpoint at main" | Sets breakpoint |
| "Save this state" | Creates QEMU snapshot |
| "Go back to the saved state" | Restores snapshot |
| "Is this a priority issue?" | Checks NVIC configuration |
| "Why did CONTROL change?" | Analyzes register history |

### Ending a Session

```
You: I'm done debugging, thanks!
```

Claude will offer to:
- Save a session report
- Clean up QEMU processes
- Save snapshots for later

---

## 5. Available Tools

When you configure the MCP server, these tools become available to Claude:

### Session Management

| Tool | Description |
|------|-------------|
| `start_session` | Start QEMU with firmware |
| `stop_session` | Stop QEMU and cleanup |
| `list_sessions` | Show active debug sessions |

### Execution Control

| Tool | Description |
|------|-------------|
| `continue_execution` | Run until breakpoint/fault |
| `step` | Single-step (into, over, out) |
| `halt` | Stop execution immediately |
| `reset` | Reset target to initial state |

### Breakpoints & Watchpoints

| Tool | Description |
|------|-------------|
| `set_breakpoint` | Set breakpoint at location |
| `set_watchpoint` | Watch memory for changes |
| `delete_breakpoint` | Remove breakpoint |
| `list_breakpoints` | Show all breakpoints |

### Inspection

| Tool | Description |
|------|-------------|
| `read_registers` | Read CPU registers |
| `read_memory` | Read memory contents |
| `backtrace` | Get stack trace |
| `list_locals` | Show local variables |
| `disassemble` | Show assembly code |

### Cortex-M Specific

| Tool | Description |
|------|-------------|
| `read_fault_registers` | Read CFSR, HFSR, MMFAR, BFAR |
| `read_exception_frame` | Parse stacked exception frame |
| `check_exception_priorities` | Verify NVIC priorities |
| `show_nvic` | Display interrupt configuration |
| `show_mpu` | Display MPU configuration |

### Analysis

| Tool | Description |
|------|-------------|
| `build_causal_chain` | Trace fault to root cause |
| `validate_fix_hypothesis` | Test fix without code changes |
| `test_fix_removal` | Check if fix is harmful |
| `find_corruption_iteration` | Binary search for timing bugs |
| `track_register_changes` | Monitor register modifications |
| `check_barrier_usage` | Static analysis for missing barriers |

### Snapshots

| Tool | Description |
|------|-------------|
| `save_snapshot` | Save full VM state |
| `restore_snapshot` | Restore to saved state |
| `list_snapshots` | Show available snapshots |
| `delete_snapshot` | Remove a snapshot |

### Comparative Debugging

| Tool | Description |
|------|-------------|
| `add_comparison_target` | Add another architecture |
| `compare_execution` | Run and diff multiple targets |

---

## 6. Example Sessions

### Example 1: Simple Crash Investigation

```
╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
My firmware is at ~/projects/sensor/build/app.elf
It crashes randomly. Can you investigate?

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
I'll start a debug session and investigate the crash.

[Calling: start_session]
  elf_path: ~/projects/sensor/build/app.elf
  machine: mps2-an385
  
Session started. QEMU running, GDB connected.

Let me save an initial checkpoint and run until it crashes.

[Calling: save_snapshot]
  name: "initial"

[Calling: continue_execution]

The firmware crashed with a HardFault at address 0x08001a3c.
Let me analyze the fault registers.

[Calling: read_fault_registers]

Fault Analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CFSR: 0x00000082
  • DACCVIOL: Data access violation
  • MMARVALID: Fault address is valid

MMFAR: 0x00000000

This is a null pointer dereference. Let me get the backtrace.

[Calling: backtrace]

Stack Trace:
#0  0x08001a3c in sensor_read (sensor=0x0) at sensor.c:45
#1  0x08002100 in main_loop () at main.c:102
#2  0x08000f54 in main () at main.c:67

The crash occurred in `sensor_read()` at sensor.c line 45.
The function was called with a NULL pointer (sensor=0x0).

Looking at the call site in main.c:102, you're likely calling
`sensor_read()` before initializing the sensor object.

Would you like me to show the source code around these locations?

╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
Yes, show me main.c around line 102

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
[Calling: show_source]
  file: main.c
  line: 102
  context: 10

main.c:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 95 │ void main_loop(void) {
 96 │     while (1) {
 97 │         if (sensor_ready) {
 98 │             // BUG: g_sensor might still be NULL here
 99 │             // if init failed but sensor_ready was set
100 │             // by an interrupt
101 │             
102 │             int value = sensor_read(g_sensor);  ← CRASH HERE
103 │             process_reading(value);
104 │         }
105 │         sleep_until_interrupt();
106 │     }
107 │ }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The bug: `sensor_ready` flag can be set by an interrupt before
`g_sensor` is initialized. You should check both conditions:

```c
if (sensor_ready && g_sensor != NULL) {
    int value = sensor_read(g_sensor);
    // ...
}
```

Or better, use a single atomic flag that's only set after full init.
```

---

### Example 2: Timing-Dependent Bug

```
╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
My IPC implementation crashes after about 30 syscalls, but the 
number varies. Sometimes 25, sometimes 50. The ELF is at 
~/projects/rtos/build/kernel.elf

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
Variable crash counts usually indicate a race condition or timing
bug. Let me investigate systematically.

[Calling: start_session]
  elf_path: ~/projects/rtos/build/kernel.elf

[Calling: save_snapshot]
  name: "initial"

First, let me run a few trials to establish the pattern.

[Running 5 trials...]
  Trial 1: Crashed at syscall 31
  Trial 2: Crashed at syscall 47
  Trial 3: Crashed at syscall 28
  Trial 4: Crashed at syscall 33
  Trial 5: Crashed at syscall 52

The high variance (28-52) suggests a race condition rather than
a deterministic bug.

Let me check the exception priorities — this is a common cause
of IPC issues.

[Calling: check_exception_priorities]

⚠️ PROBLEM DETECTED:

  Exception      Priority
  ───────────────────────
  SVCall         0x40 (64)
  PendSV         0x00 (0)   ← WRONG
  SysTick        0x80 (128)

PendSV has HIGHER priority than SVCall (lower number = higher
priority). This means PendSV can preempt SVCall handlers.

This is almost certainly your bug. Let me build the causal chain.

[Calling: build_causal_chain]
  symptom: "INVPC"

Causal Chain:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INVPC fault (stacked PC corrupted)
  └── Exception frame on wrong stack
        └── CONTROL register has wrong value (0x02 instead of 0x03)
              └── PendSV saved CONTROL during syscall elevation
                    └── PendSV preempted SVCall ← ROOT CAUSE
                          └── Priority misconfiguration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Let me validate the fix before recommending it.

[Calling: validate_fix_hypothesis]
  description: "Set PendSV to lowest priority (0xFF)"
  patches: [
    {
      address: "0xE000ED20",
      original: "00000000",
      patched: "00FF0000"
    }
  ]
  test_iterations: 100

Fix Validation Results:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Without fix: 31/100 passed (31%)
With fix:    100/100 passed (100%) ✓

New bugs introduced: None
Recommendation: APPLY FIX
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Validated fix. Add this to your RTOS initialization:

```c
void rtos_init(void) {
    // PendSV must be lowest priority to avoid preempting syscalls
    NVIC_SetPriority(PendSV_IRQn, 0xFF);
    
    // SVCall should be high priority
    NVIC_SetPriority(SVCall_IRQn, 0x00);
    
    // ... rest of init
}
```

╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
Where is the priority currently being set?

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
[Calling: search_source]
  pattern: "NVIC_SetPriority.*PendSV"

[Calling: search_source]
  pattern: "SHPR3"

Found in src/kernel/port_cm3.c:

```c
// line 87-92
void port_init(void) {
    // Configure SVCall priority
    NVIC_SetPriority(SVCall_IRQn, 0);
    
    // BUG: PendSV priority not set!
    // Defaults to 0 (highest priority)
}
```

The fix is simple — add line 93:

```c
void port_init(void) {
    NVIC_SetPriority(SVCall_IRQn, 0);
    NVIC_SetPriority(PendSV_IRQn, 0xFF);  // Add this line
}
```
```

---

### Example 3: Using Snapshots for Exploration

```
╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
I want to explore what happens at different points in my boot
sequence. Load ~/projects/boot/bootloader.elf

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
[Calling: start_session]
  elf_path: ~/projects/boot/bootloader.elf

Session started. Let me set up checkpoints at key boot stages.

[Calling: set_breakpoint]
  location: "Reset_Handler"

[Calling: set_breakpoint]  
  location: "SystemInit"

[Calling: set_breakpoint]
  location: "main"

[Calling: set_breakpoint]
  location: "boot_complete"

Breakpoints set. Running to first checkpoint...

[Calling: continue_execution]

Stopped at Reset_Handler. Saving checkpoint.

[Calling: save_snapshot]
  name: "reset"

[Calling: continue_execution]

Stopped at SystemInit. Saving checkpoint.

[Calling: save_snapshot]
  name: "system-init"

[Calling: continue_execution]

Stopped at main. Saving checkpoint.

[Calling: save_snapshot]
  name: "main-entry"

Checkpoints created:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• reset        — Just after reset vector
• system-init  — Start of SystemInit()
• main-entry   — Start of main()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You can now say things like:
- "Go back to reset"
- "What are the registers at system-init?"
- "Compare memory at main-entry vs reset"

╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
Go back to system-init and show me what SystemInit does to the
clock registers

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
[Calling: restore_snapshot]
  name: "system-init"

[Calling: read_memory]
  address: "0x40023800"  # RCC base
  length: 64

Clock registers BEFORE SystemInit:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RCC_CR:   0x00000083  (HSI on, ready)
RCC_CFGR: 0x00000000  (HSI selected, no PLL)
RCC_PLL:  0x00000000  (PLL disabled)

Now let me step through SystemInit and check after.

[Calling: set_breakpoint]
  location: "SystemInit"
  temporary: true

[Calling: continue_execution]  # Run to end of SystemInit

[Calling: read_memory]
  address: "0x40023800"
  length: 64

Clock registers AFTER SystemInit:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RCC_CR:   0x03036783  (HSE on, PLL on, ready)
RCC_CFGR: 0x0000940A  (PLL selected, APB1=/4, APB2=/2)
RCC_PLL:  0x05403608  (PLL configured for 168 MHz)

SystemInit configured:
• HSE as clock source (external crystal)
• PLL for 168 MHz system clock
• APB1 at 42 MHz, APB2 at 84 MHz

This looks correct for an STM32F4 at full speed.
```

---

### Example 4: Comparative Debugging

```
╭─────────────────────────────────────────────────────────────────╮
│ You                                                             │
╰─────────────────────────────────────────────────────────────────╯
My code works on the Cortex-M33 target but crashes on Cortex-M3.
Can you compare them?

ELF: ~/projects/portable/build/app.elf

╭─────────────────────────────────────────────────────────────────╮
│ Claude                                                          │
╰─────────────────────────────────────────────────────────────────╯
I'll run your firmware on both architectures and find where they
diverge.

[Calling: start_session]
  elf_path: ~/projects/portable/build/app.elf
  machine: mps2-an385
  name: "cortex-m3"

[Calling: add_comparison_target]
  name: "cortex-m33"
  machine: mps2-an505
  elf_path: ~/projects/portable/build/app.elf

Both targets loaded. Running comparative analysis...

[Calling: compare_execution]
  targets: ["cortex-m3", "cortex-m33"]
  breakpoints: ["main", "syscall_entry", "syscall_exit"]
  max_iterations: 50

Comparative Analysis Results:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Targets converged through 23 iterations, then diverged.

DIVERGENCE DETECTED at iteration 24:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Location: syscall_exit (0x08002340)

  Register     Cortex-M3     Cortex-M33
  ─────────────────────────────────────
  CONTROL      0x02          0x03        ← DIFFERENT
  PC           0x08002340    0x08002340
  LR           0xFFFFFFFD    0xFFFFFFFD
  
Cortex-M3 has CONTROL=0x02 (privileged, PSP)
Cortex-M33 has CONTROL=0x03 (unprivileged, PSP)

On the next iteration, Cortex-M3 crashed.
Cortex-M33 continued successfully.

This suggests an architectural difference in how CONTROL is
handled during exception return.

Let me check for missing memory barriers...

[Calling: check_barrier_usage]
  elf_path: ~/projects/portable/build/app.elf

⚠️ STATIC ANALYSIS WARNING:

  File: src/kernel/syscall.c, Line 142
  Issue: MSR CONTROL not followed by DSB+ISB
  
  The code writes to CONTROL but doesn't ensure the pipeline
  sees the new value before continuing.
  
  ARMv8-M (Cortex-M33) handles this more gracefully.
  ARMv7-M (Cortex-M3) requires explicit barriers.

Fix:
```c
// syscall.c line 142
__set_CONTROL(new_control);
__DSB();  // Add this
__ISB();  // Add this
```

This explains why it works on M33 but not M3 — different
pipeline behavior with respect to system register updates.
```

---

## 7. Troubleshooting

### MCP Server Not Appearing in Claude Desktop

**Symptom:** No "unconcealer" in the MCP server list

**Solutions:**

1. Check config file syntax:
```bash
# Validate JSON (macOS)
python3 -m json.tool < ~/Library/Application\ Support/Claude/claude_desktop_config.json

# Linux
python3 -m json.tool < ~/.config/Claude/claude_desktop_config.json
```

2. Check the debugger is installed:
```bash
# If using virtual environment
/path/to/unconcealer/.venv/bin/python -m unconcealer.cli --help

# Or if installed globally
which unconcealer
unconcealer --version
```

3. Check server starts manually:
```bash
# Test MCP protocol directly
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
    python -m unconcealer.cli mcp-server 2>/dev/null

# Should output JSON with "unconcealer" server info
```

4. Restart Claude Desktop completely (quit and reopen)

---

### "Failed to Start Session" Error

**Symptom:** Claude says it couldn't start QEMU

**Solutions:**

1. Check QEMU is installed:
```bash
qemu-system-arm --version
```

2. Check the ELF file exists and is readable:
```bash
file ~/path/to/firmware.elf
# Should say "ELF 32-bit LSB executable, ARM, ..."
```

3. Try starting QEMU manually:
```bash
qemu-system-arm -machine mps2-an385 -kernel firmware.elf -nographic -S -s
```

4. Check for port conflicts (GDB uses 1234, QMP uses 4444):
```bash
lsof -i :1234
lsof -i :4444
```

---

### GDB Connection Failures

**Symptom:** Session starts but tools fail with "GDB not connected"

**Solutions:**

1. Check GDB is installed:
```bash
gdb-multiarch --version
# or
arm-none-eabi-gdb --version
```

2. Specify GDB path in config:
```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "/path/to/unconcealer/.venv/bin/python",
      "args": [
        "-m", "unconcealer.cli", "mcp-server",
        "--gdb-path", "/usr/bin/gdb-multiarch"
      ]
    }
  }
}
```

---

### Snapshots Not Working

**Symptom:** "Failed to save snapshot" or "Snapshot not found"

**Solutions:**

1. Check disk space:
```bash
df -h /tmp
```

2. Configure snapshot directory:
```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "/path/to/unconcealer/.venv/bin/python",
      "args": ["-m", "unconcealer.cli", "mcp-server"],
      "env": {
        "DEBUGGER_SNAPSHOT_DIR": "/path/with/more/space"
      }
    }
  }
}
```

3. Note: Snapshots require QEMU to be paused. The debugger handles this automatically, but if you're seeing issues, try:
```
You: Pause execution and save a snapshot called "test"
```

---

### Slow Performance

**Symptom:** Tools take a long time to respond

**Possible causes:**

1. **Large ELF file** — Symbol loading is slow for big binaries
   - Solution: Use stripped ELF for execution, full ELF for symbols

2. **Many breakpoints** — Each breakpoint adds overhead
   - Solution: Delete unused breakpoints

3. **Antivirus interference** — Some AV slows QEMU
   - Solution: Exclude QEMU and the workspace from scanning

---

### Log Files

Enable debug logging to diagnose issues:

```json
{
  "mcpServers": {
    "unconcealer": {
      "command": "/path/to/unconcealer/.venv/bin/python",
      "args": ["-m", "unconcealer.cli", "mcp-server", "--verbose"],
      "env": {
        "DEBUGGER_LOG_LEVEL": "DEBUG",
        "DEBUGGER_LOG_FILE": "/tmp/unconcealer.log"
      }
    }
  }
}
```

Then check the log:
```bash
tail -f /tmp/unconcealer.log
```

---

## 8. Architecture

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLAUDE DESKTOP                                     │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                         Claude (LLM)                                 │  │
│   │                                                                      │  │
│   │   • Understands your debugging questions                            │  │
│   │   • Decides which tools to call                                     │  │
│   │   • Interprets results                                              │  │
│   │   • Explains findings in natural language                           │  │
│   │                                                                      │  │
│   └───────────────────────────────┬─────────────────────────────────────┘  │
│                                   │                                         │
│                                   │ MCP Protocol (JSON-RPC over stdio)      │
│                                   │                                         │
└───────────────────────────────────┼─────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                            MCP SERVER                                         │
│                     (unconcealer mcp-server)                                  │
│                                                                               │
│   ┌─────────────────────────────────────────────────────────────────────────┐│
│   │                         Tool Handlers                                    ││
│   │                                                                          ││
│   │   start_session()     read_registers()     build_causal_chain()         ││
│   │   continue_exec()     read_memory()        validate_hypothesis()        ││
│   │   set_breakpoint()    backtrace()          check_priorities()           ││
│   │   save_snapshot()     read_faults()        compare_execution()          ││
│   │                                                                          ││
│   └──────────────────────────────────┬──────────────────────────────────────┘│
│                                      │                                        │
│   ┌──────────────────────────────────┼──────────────────────────────────────┐│
│   │                         Debugger Library                                 ││
│   │                                                                          ││
│   │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   ││
│   │   │ GDBBridge   │  │QEMUControl  │  │CausalChain  │  │ Hypothesis  │   ││
│   │   │             │  │             │  │ Analyzer    │  │ Validator   │   ││
│   │   └──────┬──────┘  └──────┬──────┘  └─────────────┘  └─────────────┘   ││
│   │          │                │                                             ││
│   └──────────┼────────────────┼─────────────────────────────────────────────┘│
│              │                │                                               │
└──────────────┼────────────────┼───────────────────────────────────────────────┘
               │                │
               │ GDB/MI         │ QMP
               │ (TCP:1234)     │ (TCP:4444)
               │                │
               ▼                ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                               QEMU                                            │
│                                                                               │
│   ┌─────────────────────┐    ┌─────────────────────┐                         │
│   │     GDB Stub        │    │     QMP Server      │                         │
│   │     (gdbserver)     │    │     (control)       │                         │
│   └──────────┬──────────┘    └──────────┬──────────┘                         │
│              │                          │                                     │
│              └────────────┬─────────────┘                                     │
│                           │                                                   │
│              ┌────────────┴────────────┐                                     │
│              │   Emulated Target       │                                     │
│              │   (Cortex-M3/M4/M33)    │                                     │
│              │                         │                                     │
│              │   ┌─────────────────┐   │                                     │
│              │   │ Your Firmware   │   │                                     │
│              │   │ (ELF loaded)    │   │                                     │
│              │   └─────────────────┘   │                                     │
│              └─────────────────────────┘                                     │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow for a Query

```
1. You type: "Why did it crash?"
                    │
                    ▼
2. Claude Desktop sends your message to Claude (LLM in cloud)
                    │
                    ▼
3. Claude decides to call tools: read_fault_registers, backtrace
                    │
                    ▼
4. Claude Desktop invokes MCP server via stdio:
   {"method": "tools/call", "params": {"name": "read_fault_registers"}}
                    │
                    ▼
5. MCP server calls debugger library:
   target = CortexMTarget(gdb)
   result = await target.read_fault_registers()
                    │
                    ▼
6. Library sends GDB/MI commands to QEMU:
   -data-read-memory-bytes 0xE000ED28 16
                    │
                    ▼
7. QEMU reads from emulated Cortex-M fault registers
                    │
                    ▼
8. Results flow back up the chain to Claude
                    │
                    ▼
9. Claude interprets: "CFSR=0x00020000 means INVPC fault"
                    │
                    ▼
10. Claude responds to you in natural language
```

### Security Model

| Component | Runs Where | Network Access | File Access |
|-----------|------------|----------------|-------------|
| Claude Desktop | Your machine | Anthropic API only | Config files |
| MCP Server | Your machine | localhost only | Your ELF files |
| QEMU | Your machine | None (isolated) | Your ELF files |
| GDB | Your machine | localhost only | Your ELF files |

**Your firmware never leaves your machine.** Only your conversation goes to Claude's servers. Tool results are processed locally.

---

## Appendix: Quick Reference

### Starting a Session

```
"Debug ~/path/to/firmware.elf"
"Load my firmware, it's an STM32F4 at path/to/file.elf"
"Start a debug session with firmware.elf using Cortex-M3"
```

### Running and Stopping

```
"Run until it crashes"
"Continue"
"Stop / Halt / Pause"
"Step into the next function"
"Step over this line"
"Reset the target"
```

### Breakpoints

```
"Set a breakpoint at main"
"Break when we reach sensor_read"
"Set a breakpoint at address 0x08001234"
"Watch variable sensor_value for changes"
"Delete all breakpoints"
```

### Inspection

```
"Show me the registers"
"What's in R3?"
"Show the backtrace"
"What's at memory address 0x20000000?"
"Disassemble the current function"
"Show local variables"
```

### Fault Analysis

```
"What caused this crash?"
"Read the fault registers"
"Explain this HardFault"
"Check the exception priorities"
"Is this a priority configuration issue?"
```

### Snapshots

```
"Save this state as 'before-bug'"
"Go back to the 'before-bug' snapshot"
"List all snapshots"
"Delete snapshot 'test'"
```

### Analysis

```
"Build a causal chain for this crash"
"Why did the CONTROL register change?"
"Validate this fix hypothesis"
"Find when the corruption first occurred"
"Compare behavior between Cortex-M3 and Cortex-M33"
```

### Session Management

```
"I'm done debugging"
"Save a report of this session"
"Clean up and exit"
```

---

## Appendix: Test Firmware

The repository includes a pre-built test firmware for validation:

```
test_fw/target/thumbv7m-none-eabi/release/test_fw
```

### What the Test Firmware Does

The test firmware (`test_fw/src/main.rs`) is a minimal Cortex-M3 program that:

1. Initializes a `TEST_VALUE` variable to `0x12345678`
2. Runs an infinite loop incrementing a `COUNTER` variable
3. Includes a `test_function()` you can set breakpoints on
4. Has a `trigger_hardfault()` function to test crash analysis

### Test Commands to Try

```
# Basic session
"Load test_fw/target/thumbv7m-none-eabi/release/test_fw for Cortex-M3"
"Show me the registers"
"Read 16 bytes at address 0x20000000"

# Breakpoints and stepping
"Set a breakpoint at main"
"Set a breakpoint at test_function"
"Continue until we hit test_function"
"Show the backtrace"

# Memory inspection
"What's the value of COUNTER?"
"Watch the COUNTER variable change over a few iterations"

# Snapshots (time travel)
"Save snapshot as before_loop"
"Continue for a while"
"What's COUNTER now?"
"Restore to before_loop"
"What's COUNTER now?" (should be back to earlier value)

# Architecture-specific analysis
"Read the fault registers"
"Check interrupt priorities"
"Show memory protection configuration"
```

### Rebuilding the Test Firmware

If you need to rebuild (requires Rust):

```bash
cd test_fw

# Install ARM target
rustup target add thumbv7m-none-eabi

# Build
cargo build --release

# Output at: target/thumbv7m-none-eabi/release/test_fw
```

---

*Document Version 2.0 — January 2026*
