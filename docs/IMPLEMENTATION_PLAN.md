# Implementation Plan: Claude Desktop MCP Server Support

**Target:** Full support for CLAUDE-DESKTOP.md usage model
**Date:** January 2026

---

## Executive Summary

This plan covers implementing the complete Claude Desktop integration as described in `CLAUDE-DESKTOP.md`. The implementation is divided into 6 phases, with a new **Phase 4: Architecture Abstraction** that enables multi-architecture support.

### Current State (What We Have)

- Basic MCP server (`create_debug_server()`)
- 14 debug tools: read_registers, read_memory, write_memory, continue_execution, step, step_over, halt, reset, set_breakpoint, delete_breakpoint, backtrace, evaluate, save_snapshot, load_snapshot
- QEMU+GDB infrastructure with `DebugSession`
- CLI with `debug` and `analyze` commands
- Model provider abstraction (Claude, OpenAI-compatible)

### Target State (What CLAUDE-DESKTOP.md Describes)

- `mcp-server` CLI command for Claude Desktop stdio integration
- Session management (multi-session support)
- Extended debug tools (watchpoints, disassembly, locals)
- **Multi-architecture support** (ARM Cortex-M, RISC-V, extensible)
- Architecture-specific fault analysis tools
- Advanced analysis tools (causal chains, hypothesis validation)
- Comparative debugging (cross-architecture comparison)
- Source code navigation tools

### Supported Architectures

| Architecture | QEMU System | Example Machines |
|--------------|-------------|------------------|
| ARM Cortex-M0/M0+ | qemu-system-arm | lm3s6965evb |
| ARM Cortex-M3 | qemu-system-arm | mps2-an385, lm3s6965evb |
| ARM Cortex-M4 | qemu-system-arm | netduinoplus2 |
| ARM Cortex-M33 | qemu-system-arm | mps2-an505 |
| RISC-V RV32 | qemu-system-riscv32 | sifive_e, virt |
| RISC-V RV64 | qemu-system-riscv64 | sifive_u, virt |
| Xtensa (ESP32) | qemu-system-xtensa | esp32 (future) |

---

## Phase 1: MCP Server CLI Command

**Goal:** Enable `unconcealer mcp-server` command that Claude Desktop can spawn

### Tasks

1. **Add `mcp-server` command to CLI** (`src/unconcealer/cli.py`)
   ```python
   @app.command()
   def mcp_server(
       gdb_path: Optional[str] = typer.Option(None),
       qemu_path: Optional[str] = typer.Option(None),
       workspace: Optional[str] = typer.Option(None),
       verbose: bool = typer.Option(False),
   ) -> None:
       """Run MCP server for Claude Desktop integration."""
   ```

2. **Create stdio transport adapter** (`src/unconcealer/mcp/stdio_server.py`)
   - Wrap existing MCP server with stdio I/O
   - Handle JSON-RPC over stdin/stdout
   - Logging to stderr (not stdout - would break protocol)

3. **Implement session manager** (`src/unconcealer/mcp/session_manager.py`)
   - Track multiple debug sessions
   - Auto-cleanup on disconnect
   - Session state persistence

4. **Add configuration support**
   - Environment variables: `DEBUGGER_LOG_LEVEL`, `DEBUGGER_LOG_FILE`, `DEBUGGER_SNAPSHOT_DIR`
   - Command-line options for paths

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/unconcealer/cli.py` | Modify | Add `mcp-server` command |
| `src/unconcealer/mcp/__init__.py` | Create | MCP module init |
| `src/unconcealer/mcp/stdio_server.py` | Create | Stdio transport |
| `src/unconcealer/mcp/session_manager.py` | Create | Multi-session support |
| `tests/test_mcp_server.py` | Create | MCP server tests |

### Success Criteria

- [ ] `unconcealer mcp-server` runs without error
- [ ] Claude Desktop can connect and list tools
- [ ] Basic tool calls work over stdio

---

## Phase 2: Session Management Tools

**Goal:** Allow Claude to start/stop debug sessions dynamically

### New Tools

| Tool | Description | Implementation |
|------|-------------|----------------|
| `start_session` | Start QEMU with firmware | Creates new DebugSession |
| `stop_session` | Stop QEMU and cleanup | Terminates DebugSession |
| `list_sessions` | Show active sessions | Returns session metadata |

### Tasks

1. **Implement `start_session` tool**
   ```python
   @tool()
   async def start_session(
       elf_path: str,
       machine: str = "lm3s6965evb",
       cpu: str = "cortex-m3",
       name: Optional[str] = None,
   ) -> dict:
       """Start a new debug session with QEMU."""
   ```

2. **Implement `stop_session` tool**
   ```python
   @tool()
   async def stop_session(name: str) -> dict:
       """Stop a debug session and cleanup resources."""
   ```

3. **Implement `list_sessions` tool**
   ```python
   @tool()
   async def list_sessions() -> list[dict]:
       """List all active debug sessions."""
   ```

4. **Update existing tools to be session-aware**
   - Add optional `session` parameter to all tools
   - Default to "current" session

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/unconcealer/agent/tools/session.py` | Create | Session management tools |
| `src/unconcealer/agent/tools/__init__.py` | Modify | Export new tools |
| `src/unconcealer/mcp/session_manager.py` | Modify | Add session tracking |
| `tests/test_session_tools.py` | Create | Session tool tests |

### Success Criteria

- [ ] Claude can start a session by specifying ELF path
- [ ] Multiple concurrent sessions supported
- [ ] Sessions properly cleaned up on stop

---

## Phase 3: Extended Debug Tools

**Goal:** Add missing debug capabilities

### New Tools

| Tool | Description | Priority |
|------|-------------|----------|
| `set_watchpoint` | Watch memory for changes | High |
| `list_breakpoints` | Show all breakpoints | High |
| `list_locals` | Show local variables | Medium |
| `disassemble` | Show assembly code | High |
| `show_source` | Show source code with context | Medium |
| `search_source` | Search source code | Low |

### Tasks

1. **Implement watchpoint support** (`src/unconcealer/agent/tools/debug.py`)
   ```python
   @tool()
   async def set_watchpoint(
       address: str,
       size: int = 4,
       access: str = "write",  # read, write, access
   ) -> dict:
       """Set a watchpoint on memory address."""
   ```

2. **Implement `list_breakpoints`**
   ```python
   @tool()
   async def list_breakpoints() -> list[dict]:
       """List all active breakpoints and watchpoints."""
   ```

3. **Implement `disassemble`**
   ```python
   @tool()
   async def disassemble(
       location: str,  # function name or address
       count: int = 20,
   ) -> str:
       """Disassemble instructions at location."""
   ```

4. **Implement `list_locals`**
   ```python
   @tool()
   async def list_locals() -> list[dict]:
       """List local variables in current frame."""
   ```

5. **Extend snapshot management**
   - `list_snapshots` - Show all saved snapshots
   - `delete_snapshot` - Remove a snapshot

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/unconcealer/agent/tools/debug.py` | Modify | Add new debug tools |
| `src/unconcealer/tools/gdb_bridge.py` | Modify | Add GDB commands |
| `tests/test_debug_tools.py` | Modify | Add tests |

### Success Criteria

- [ ] Watchpoints trigger on memory access
- [ ] Disassembly shows readable output with symbols
- [ ] Local variables shown with values

---

## Phase 4: Architecture Abstraction Layer

**Goal:** Create a pluggable architecture system that enables multi-architecture support

### Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TargetArchitecture (Protocol)                 │
├─────────────────────────────────────────────────────────────────────┤
│  name: str                                                           │
│  register_names: list[str]                                           │
│  pointer_size: int                                                   │
│                                                                      │
│  + read_fault_state() -> FaultState                                 │
│  + decode_exception_frame(sp: int) -> ExceptionFrame                │
│  + check_interrupt_config() -> InterruptAnalysis                    │
│  + get_memory_protection() -> MemoryProtection                      │
│  + analyze_crash() -> CrashAnalysis                                 │
└─────────────────────────────────────────────────────────────────────┘
                    ▲                           ▲
                    │                           │
        ┌───────────┴───────────┐   ┌───────────┴───────────┐
        │   CortexMTarget       │   │   RiscVTarget         │
        ├───────────────────────┤   ├───────────────────────┤
        │ - CFSR, HFSR, etc.    │   │ - mcause, mtval       │
        │ - NVIC analysis       │   │ - PLIC/CLIC analysis  │
        │ - MPU decoding        │   │ - PMP decoding        │
        │ - Thumb bit handling  │   │ - Compressed insn     │
        └───────────────────────┘   └───────────────────────┘
```

### Tasks

1. **Define architecture protocol** (`src/unconcealer/arch/base.py`)
   ```python
   from typing import Protocol, runtime_checkable
   from dataclasses import dataclass

   @dataclass
   class FaultState:
       """Architecture-agnostic fault information."""
       fault_type: str  # "access_violation", "illegal_instruction", etc.
       fault_address: Optional[int]
       is_valid: bool
       raw_registers: dict[str, int]
       decoded: dict[str, str]  # Human-readable explanations

   @dataclass
   class ExceptionFrame:
       """Stacked exception frame."""
       registers: dict[str, int]
       return_address: int
       stack_pointer: int

   @dataclass
   class InterruptAnalysis:
       """Interrupt controller analysis."""
       enabled: list[dict]
       pending: list[dict]
       priorities: dict[str, int]
       warnings: list[str]  # e.g., "PendSV has higher priority than SVCall"

   @runtime_checkable
   class TargetArchitecture(Protocol):
       """Protocol for architecture-specific debugging support."""

       name: str
       register_names: list[str]
       pointer_size: int  # 4 for 32-bit, 8 for 64-bit

       async def read_fault_state(self, session) -> FaultState:
           """Read and decode fault/exception state."""
           ...

       async def decode_exception_frame(
           self, session, stack_pointer: Optional[int] = None
       ) -> ExceptionFrame:
           """Parse the stacked exception/trap frame."""
           ...

       async def check_interrupt_config(self, session) -> InterruptAnalysis:
           """Analyze interrupt controller configuration."""
           ...

       async def get_memory_protection(self, session) -> dict:
           """Read MPU/PMP configuration."""
           ...

       async def analyze_crash(self, session) -> dict:
           """Perform architecture-specific crash analysis."""
           ...
   ```

2. **Implement ARM Cortex-M target** (`src/unconcealer/arch/cortex_m.py`)
   ```python
   class CortexMTarget:
       """ARM Cortex-M architecture support."""

       name = "cortex-m"
       register_names = ["r0", "r1", ..., "r12", "sp", "lr", "pc", "xpsr"]
       pointer_size = 4

       # System Control Block addresses
       CFSR  = 0xE000ED28
       HFSR  = 0xE000ED2C
       MMFAR = 0xE000ED34
       BFAR  = 0xE000ED38
       SHPR1 = 0xE000ED18
       SHPR2 = 0xE000ED1C
       SHPR3 = 0xE000ED20

       # NVIC addresses
       NVIC_ISER = 0xE000E100  # Interrupt Set Enable
       NVIC_ICER = 0xE000E180  # Interrupt Clear Enable
       NVIC_ISPR = 0xE000E200  # Interrupt Set Pending
       NVIC_IPR  = 0xE000E400  # Interrupt Priority

       async def read_fault_state(self, session) -> FaultState:
           cfsr = await session.read_memory(self.CFSR, 4)
           hfsr = await session.read_memory(self.HFSR, 4)
           mmfar = await session.read_memory(self.MMFAR, 4)
           bfar = await session.read_memory(self.BFAR, 4)
           return self._decode_fault_registers(cfsr, hfsr, mmfar, bfar)

       def _decode_cfsr(self, value: int) -> dict[str, str]:
           """Decode CFSR bits into human-readable messages."""
           decoded = {}
           # MemManage faults (bits 0-7)
           if value & 0x01: decoded["IACCVIOL"] = "Instruction access violation"
           if value & 0x02: decoded["DACCVIOL"] = "Data access violation"
           if value & 0x08: decoded["MUNSTKERR"] = "MemManage fault on unstacking"
           if value & 0x10: decoded["MSTKERR"] = "MemManage fault on stacking"
           if value & 0x80: decoded["MMARVALID"] = "MMFAR holds valid address"
           # BusFault (bits 8-15)
           if value & 0x0100: decoded["IBUSERR"] = "Instruction bus error"
           if value & 0x0200: decoded["PRECISERR"] = "Precise data bus error"
           if value & 0x0400: decoded["IMPRECISERR"] = "Imprecise data bus error"
           if value & 0x8000: decoded["BFARVALID"] = "BFAR holds valid address"
           # UsageFault (bits 16-25)
           if value & 0x010000: decoded["UNDEFINSTR"] = "Undefined instruction"
           if value & 0x020000: decoded["INVSTATE"] = "Invalid state (Thumb)"
           if value & 0x040000: decoded["INVPC"] = "Invalid PC load"
           if value & 0x080000: decoded["NOCP"] = "No coprocessor"
           if value & 0x100000: decoded["UNALIGNED"] = "Unaligned access"
           if value & 0x200000: decoded["DIVBYZERO"] = "Divide by zero"
           return decoded
   ```

3. **Implement RISC-V target** (`src/unconcealer/arch/riscv.py`)
   ```python
   class RiscVTarget:
       """RISC-V architecture support."""

       name = "riscv"
       register_names = ["zero", "ra", "sp", "gp", "tp",
                         "t0", "t1", "t2", "s0", "s1",
                         "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
                         "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9",
                         "s10", "s11", "t3", "t4", "t5", "t6", "pc"]
       pointer_size = 4  # RV32; set to 8 for RV64

       # CSR addresses (accessible via GDB)
       MCAUSE = 0x342   # Machine trap cause
       MTVAL  = 0x343   # Machine trap value
       MEPC   = 0x341   # Machine exception PC
       MSTATUS = 0x300  # Machine status
       MIE    = 0x304   # Machine interrupt enable
       MIP    = 0x344   # Machine interrupt pending

       # PLIC addresses (platform-dependent)
       PLIC_BASE = 0x0C000000  # Common for QEMU virt

       async def read_fault_state(self, session) -> FaultState:
           mcause = await self._read_csr(session, "mcause")
           mtval = await self._read_csr(session, "mtval")
           mepc = await self._read_csr(session, "mepc")
           return self._decode_trap(mcause, mtval, mepc)

       def _decode_mcause(self, value: int) -> dict:
           """Decode mcause into trap type."""
           interrupt = (value >> 31) & 1
           code = value & 0x7FFFFFFF

           if interrupt:
               INTERRUPT_CODES = {
                   3: "Machine software interrupt",
                   7: "Machine timer interrupt",
                   11: "Machine external interrupt",
               }
               return {"type": "interrupt", "name": INTERRUPT_CODES.get(code, f"Unknown ({code})")}
           else:
               EXCEPTION_CODES = {
                   0: "Instruction address misaligned",
                   1: "Instruction access fault",
                   2: "Illegal instruction",
                   3: "Breakpoint",
                   4: "Load address misaligned",
                   5: "Load access fault",
                   6: "Store address misaligned",
                   7: "Store access fault",
                   8: "Environment call from U-mode",
                   11: "Environment call from M-mode",
                   12: "Instruction page fault",
                   13: "Load page fault",
                   15: "Store page fault",
               }
               return {"type": "exception", "name": EXCEPTION_CODES.get(code, f"Unknown ({code})")}

       async def check_interrupt_config(self, session) -> InterruptAnalysis:
           """Analyze PLIC configuration for RISC-V."""
           # Read MIE/MIP for machine-level interrupts
           mie = await self._read_csr(session, "mie")
           mip = await self._read_csr(session, "mip")

           enabled = []
           pending = []
           warnings = []

           # Decode machine interrupts
           if mie & (1 << 3): enabled.append({"name": "MSI", "desc": "Machine Software"})
           if mie & (1 << 7): enabled.append({"name": "MTI", "desc": "Machine Timer"})
           if mie & (1 << 11): enabled.append({"name": "MEI", "desc": "Machine External"})

           if mip & (1 << 3): pending.append({"name": "MSI"})
           if mip & (1 << 7): pending.append({"name": "MTI"})
           if mip & (1 << 11): pending.append({"name": "MEI"})

           return InterruptAnalysis(
               enabled=enabled,
               pending=pending,
               priorities={},  # PLIC priorities would go here
               warnings=warnings,
           )
   ```

4. **Create architecture registry** (`src/unconcealer/arch/__init__.py`)
   ```python
   from unconcealer.arch.base import TargetArchitecture
   from unconcealer.arch.cortex_m import CortexMTarget
   from unconcealer.arch.riscv import RiscVTarget

   # Architecture registry
   ARCHITECTURES: dict[str, type[TargetArchitecture]] = {
       "cortex-m": CortexMTarget,
       "cortex-m0": CortexMTarget,
       "cortex-m3": CortexMTarget,
       "cortex-m4": CortexMTarget,
       "cortex-m33": CortexMTarget,
       "riscv": RiscVTarget,
       "riscv32": RiscVTarget,
       "riscv64": RiscVTarget,
   }

   def get_architecture(name: str) -> TargetArchitecture:
       """Get architecture handler by name."""
       arch_class = ARCHITECTURES.get(name.lower())
       if arch_class is None:
           raise ValueError(f"Unknown architecture: {name}. "
                          f"Supported: {list(ARCHITECTURES.keys())}")
       return arch_class()

   def detect_architecture(cpu: str, machine: str) -> str:
       """Auto-detect architecture from QEMU cpu/machine."""
       cpu_lower = cpu.lower()
       if "cortex" in cpu_lower:
           return "cortex-m"
       if "rv32" in cpu_lower or "riscv32" in machine.lower():
           return "riscv32"
       if "rv64" in cpu_lower or "riscv64" in machine.lower():
           return "riscv64"
       if "sifive" in machine.lower():
           return "riscv"
       return "cortex-m"  # Default
   ```

5. **Create architecture-aware tools** (`src/unconcealer/agent/tools/arch_tools.py`)
   ```python
   @tool()
   async def read_fault_registers(architecture: Optional[str] = None) -> dict:
       """Read fault/exception state for the current architecture.

       Works across ARM Cortex-M (CFSR/HFSR), RISC-V (mcause/mtval), etc.
       """
       session = get_current_session()
       arch = session.architecture  # Auto-detected or specified
       fault_state = await arch.read_fault_state(session)
       return fault_state.to_dict()

   @tool()
   async def check_interrupt_priorities() -> dict:
       """Check interrupt configuration and detect issues.

       ARM: Checks NVIC priorities (e.g., PendSV vs SVCall)
       RISC-V: Checks PLIC/CLIC configuration
       """
       session = get_current_session()
       arch = session.architecture
       analysis = await arch.check_interrupt_config(session)
       return {
           "enabled": analysis.enabled,
           "pending": analysis.pending,
           "priorities": analysis.priorities,
           "warnings": analysis.warnings,
       }
   ```

### Cortex-M Specific Details

| Register | Address | Description |
|----------|---------|-------------|
| CFSR | 0xE000ED28 | Configurable Fault Status |
| HFSR | 0xE000ED2C | HardFault Status |
| MMFAR | 0xE000ED34 | MemManage Fault Address |
| BFAR | 0xE000ED38 | BusFault Address |
| SHPR3 | 0xE000ED20 | System Handler Priority 3 |
| NVIC_ISER | 0xE000E100 | Interrupt Set Enable |
| NVIC_IPR | 0xE000E400 | Interrupt Priority |

### RISC-V Specific Details

| CSR | Number | Description |
|-----|--------|-------------|
| mcause | 0x342 | Machine trap cause |
| mtval | 0x343 | Machine trap value |
| mepc | 0x341 | Machine exception PC |
| mstatus | 0x300 | Machine status |
| mie | 0x304 | Machine interrupt enable |
| mip | 0x344 | Machine interrupt pending |

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/unconcealer/arch/__init__.py` | Create | Architecture registry |
| `src/unconcealer/arch/base.py` | Create | Protocol and dataclasses |
| `src/unconcealer/arch/cortex_m.py` | Create | ARM Cortex-M support |
| `src/unconcealer/arch/riscv.py` | Create | RISC-V support |
| `src/unconcealer/agent/tools/arch_tools.py` | Create | Architecture-aware tools |
| `src/unconcealer/core/session.py` | Modify | Add architecture detection |
| `tests/test_arch_cortex_m.py` | Create | Cortex-M tests |
| `tests/test_arch_riscv.py` | Create | RISC-V tests |

### Success Criteria

- [ ] Architecture auto-detected from CPU/machine
- [ ] Fault registers work for both Cortex-M and RISC-V
- [ ] Interrupt analysis works for NVIC and PLIC
- [ ] New architectures can be added by implementing protocol

---

## Phase 5: Architecture-Specific Tools

**Goal:** Implement architecture-specific tools using the abstraction layer

### Universal Tools (use architecture abstraction)

| Tool | Description | Cortex-M | RISC-V |
|------|-------------|----------|--------|
| `read_fault_registers` | Read fault state | CFSR, HFSR, MMFAR, BFAR | mcause, mtval, mepc |
| `read_exception_frame` | Parse stacked frame | R0-R3, R12, LR, PC, xPSR | ra, sp, gp, a0-a7, etc. |
| `check_interrupt_priorities` | Verify config | NVIC priorities | PLIC priorities |
| `show_interrupt_controller` | Display config | NVIC enabled/pending | PLIC/CLIC state |
| `show_memory_protection` | Display MPU/PMP | MPU regions | PMP entries |

### Tasks

1. **Implement unified fault tool**
   ```python
   @tool()
   async def read_fault_registers() -> dict:
       """Read fault/exception state.

       Returns architecture-appropriate fault information:
       - ARM Cortex-M: CFSR, HFSR, MMFAR, BFAR with bit decoding
       - RISC-V: mcause, mtval, mepc with trap type decoding
       """
   ```

2. **Implement unified exception frame tool**
   ```python
   @tool()
   async def read_exception_frame(stack_pointer: Optional[str] = None) -> dict:
       """Parse the stacked exception/trap frame.

       Returns architecture-appropriate frame:
       - ARM Cortex-M: R0-R3, R12, LR, PC, xPSR (8 words)
       - RISC-V: Full register set from trap entry
       """
   ```

3. **Implement unified interrupt tool**
   ```python
   @tool()
   async def show_interrupt_controller() -> dict:
       """Display interrupt controller configuration.

       - ARM Cortex-M: NVIC enabled, pending, priorities
       - RISC-V: PLIC/CLIC enabled, pending, thresholds
       """
   ```

4. **Implement unified memory protection tool**
   ```python
   @tool()
   async def show_memory_protection() -> dict:
       """Display memory protection configuration.

       - ARM Cortex-M: MPU regions with permissions
       - RISC-V: PMP entries with permissions
       """
   ```

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/unconcealer/agent/tools/arch_tools.py` | Modify | Add all arch tools |
| `tests/test_arch_tools.py` | Create | Unified tool tests |

### Success Criteria

- [ ] All tools work transparently across architectures
- [ ] Output format is consistent (architecture differences in details)
- [ ] Warnings/analysis adapted per architecture

---

## Phase 6: Advanced Analysis Tools

**Goal:** Add sophisticated debugging capabilities with cross-architecture support

### New Tools

| Tool | Description | Complexity |
|------|-------------|------------|
| `build_causal_chain` | Trace fault to root cause | High |
| `validate_fix_hypothesis` | Test fix without code changes | High |
| `find_corruption_iteration` | Binary search for timing bugs | Medium |
| `track_register_changes` | Monitor register modifications | Medium |
| `check_barrier_usage` | Static analysis for missing barriers | Medium |
| `add_comparison_target` | Add another architecture | High |
| `compare_execution` | Run and diff multiple targets | High |

### Tasks

1. **Implement causal chain analysis** (`src/unconcealer/agent/tools/analysis.py`)
   ```python
   @tool()
   async def build_causal_chain(symptom: str) -> dict:
       """Build a causal chain from symptom to root cause.

       Uses architecture-specific fault analysis to trace the
       sequence of events leading to a crash.

       Example output (Cortex-M):
         INVPC fault
         └── Exception frame on wrong stack
               └── CONTROL register wrong (0x02 vs 0x03)
                     └── PendSV preempted SVCall
                           └── Priority misconfiguration

       Example output (RISC-V):
         Illegal instruction trap
         └── PC points to .data section
               └── Stack overflow corrupted return address
                     └── Deep recursion in parse_json()
       """
   ```

2. **Implement hypothesis validation**
   ```python
   @tool()
   async def validate_fix_hypothesis(
       description: str,
       patches: list[dict],  # {address, original, patched}
       test_iterations: int = 100,
   ) -> dict:
       """Test a fix hypothesis using memory patches.

       Works across architectures - patches memory at runtime.
       """
   ```

3. **Implement corruption finder**
   ```python
   @tool()
   async def find_corruption_iteration(
       address: str,
       expected_value: str,
       max_iterations: int = 1000,
   ) -> dict:
       """Binary search to find when corruption first occurs."""
   ```

4. **Implement register tracking**
   ```python
   @tool()
   async def track_register_changes(
       registers: list[str],
       breakpoint: str,
       iterations: int = 10,
   ) -> list[dict]:
       """Track how registers change across iterations.

       Register names are architecture-aware:
       - Cortex-M: r0-r12, sp, lr, pc, control
       - RISC-V: x0-x31 or ABI names (a0, s0, etc.)
       """
   ```

5. **Implement cross-architecture comparative debugging** (`src/unconcealer/agent/tools/comparative.py`)
   ```python
   @tool()
   async def add_comparison_target(
       name: str,
       machine: str,
       cpu: str,
       elf_path: str,
   ) -> dict:
       """Add a comparison target (can be different architecture).

       Enables comparing:
       - Same code on Cortex-M3 vs Cortex-M33
       - Same code on ARM vs RISC-V (portable code)
       """

   @tool()
   async def compare_execution(
       targets: list[str],
       breakpoints: list[str],
       max_iterations: int = 50,
   ) -> dict:
       """Compare execution between targets, find divergence.

       For cross-architecture comparison, uses semantic matching:
       - Function names (from symbols)
       - Memory contents (at equivalent addresses)
       - Logical flow (not exact register values)
       """
   ```

### Cross-Architecture Analysis

The analysis tools use the architecture abstraction to provide consistent
behavior across different targets:

| Analysis | Cortex-M | RISC-V |
|----------|----------|--------|
| Fault cause | CFSR/HFSR bits | mcause code |
| Fault address | MMFAR/BFAR | mtval |
| Interrupt issue | NVIC priority inversion | PLIC threshold |
| Memory violation | MPU region | PMP entry |
| Missing barrier | DSB/ISB needed | FENCE needed |

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/unconcealer/agent/tools/analysis.py` | Create | Analysis tools |
| `src/unconcealer/agent/tools/comparative.py` | Create | Comparative debugging |
| `src/unconcealer/core/hypothesis.py` | Create | Hypothesis validation logic |
| `tests/test_analysis_tools.py` | Create | Analysis tests |

### Success Criteria

- [ ] Causal chains work for both Cortex-M and RISC-V faults
- [ ] Fix validation runs multiple trials across architectures
- [ ] Cross-architecture comparison identifies semantic divergence

---

## Implementation Order

```
Phase 1: MCP Server CLI            [Week 1]
    ↓
Phase 2: Session Management        [Week 1-2]
    ↓
Phase 3: Extended Debug            [Week 2]
    ↓
Phase 4: Architecture Abstraction  [Week 2-3]  ← NEW
    ↓
Phase 5: Architecture-Specific     [Week 3]
    ↓
Phase 6: Analysis Tools            [Week 3-4]
```

### Dependencies

```
                    ┌─────────────────────┐
                    │ Phase 1: MCP Server │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Phase 2: Sessions   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Phase 3: Debug      │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Phase 4: Arch Layer │ ← Core abstraction
                    └──────────┬──────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
┌─────────▼─────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│ Cortex-M Support  │ │ RISC-V Support  │ │ Future Arch...  │
└───────────────────┘ └─────────────────┘ └─────────────────┘
          │                    │
          └──────────┬─────────┘
                     │
          ┌──────────▼──────────┐
          │ Phase 5: Arch Tools │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │ Phase 6: Analysis   │
          └─────────────────────┘
```

- Phase 2 depends on Phase 1 (session manager)
- Phase 4 depends on Phase 3 (memory read infrastructure)
- Phase 5 depends on Phase 4 (uses architecture abstraction)
- Phase 6 depends on Phase 5 (uses fault analysis for causal chains)
- New architectures can be added at any time after Phase 4

---

## Testing Strategy

### Unit Tests

- Each new tool gets unit tests with mocked GDB/QEMU
- Architecture-specific register decoding tested with known values
- Protocol compliance tests for architecture abstraction

### Architecture-Specific Tests

| Test | Cortex-M | RISC-V |
|------|----------|--------|
| Fault decoding | CFSR=0x00020000 → INVPC | mcause=2 → Illegal insn |
| Exception frame | 8-word ARM frame | RISC-V trap frame |
| Interrupt analysis | NVIC priority inversion | PLIC threshold issues |
| Memory protection | MPU region parse | PMP entry parse |

### Integration Tests

- Full MCP server integration with actual QEMU
- Multi-session tests
- Fault injection and detection tests
- Cross-architecture session tests (start ARM, then RISC-V)

### End-to-End Tests

- Test with Claude Desktop (manual)
- Verify example sessions from CLAUDE-DESKTOP.md work
- Test cross-architecture comparative debugging

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUGGER_LOG_LEVEL` | Logging level | INFO |
| `DEBUGGER_LOG_FILE` | Log file path | stderr |
| `DEBUGGER_SNAPSHOT_DIR` | Snapshot storage | /tmp/unconcealer |
| `DEBUGGER_GDB_PATH` | GDB executable | gdb-multiarch |
| `DEBUGGER_QEMU_ARM_PATH` | ARM QEMU | qemu-system-arm |
| `DEBUGGER_QEMU_RISCV32_PATH` | RISC-V 32-bit QEMU | qemu-system-riscv32 |
| `DEBUGGER_QEMU_RISCV64_PATH` | RISC-V 64-bit QEMU | qemu-system-riscv64 |

### Claude Desktop Config Example

```json
{
  "mcpServers": {
    "embedded-debugger": {
      "command": "unconcealer",
      "args": ["mcp-server"],
      "env": {
        "DEBUGGER_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Multi-Architecture Config Example

```json
{
  "mcpServers": {
    "embedded-debugger": {
      "command": "unconcealer",
      "args": ["mcp-server"],
      "env": {
        "DEBUGGER_GDB_PATH": "/usr/bin/gdb-multiarch",
        "DEBUGGER_QEMU_ARM_PATH": "/usr/bin/qemu-system-arm",
        "DEBUGGER_QEMU_RISCV32_PATH": "/usr/bin/qemu-system-riscv32",
        "DEBUGGER_QEMU_RISCV64_PATH": "/usr/bin/qemu-system-riscv64"
      }
    }
  }
}
```

---

## Open Questions

1. **Source code access:** Should we include `show_source` / `search_source` tools? This requires access to source files which may not be on the same machine as the ELF.

2. **Static analysis:** The `check_barrier_usage` tool requires ELF analysis. Should we integrate with external tools (objdump) or implement our own? Consider architecture-specific disassemblers.

3. **Resource limits:** How many concurrent sessions should we support? What's the memory/CPU budget per session?

4. **Future architectures:** Which architectures should we prioritize after Cortex-M and RISC-V?
   - Xtensa (ESP32) - popular for IoT
   - AVR (Arduino) - educational
   - AArch64 (Cortex-A) - Linux embedded

---

## Appendix: Tool Summary

### Currently Implemented (14 tools)

1. read_registers
2. read_memory
3. write_memory
4. continue_execution
5. step
6. step_over
7. halt
8. reset
9. set_breakpoint
10. delete_breakpoint
11. backtrace
12. evaluate
13. save_snapshot
14. load_snapshot

### To Implement (Phase 1-6)

**Phase 2 - Session Management (3 tools)**
1. start_session
2. stop_session
3. list_sessions

**Phase 3 - Extended Debug (6 tools)**
1. set_watchpoint
2. list_breakpoints
3. list_locals
4. disassemble
5. list_snapshots
6. delete_snapshot

**Phase 4 - Architecture Abstraction (0 new tools, infrastructure only)**
- TargetArchitecture protocol
- CortexMTarget implementation
- RiscVTarget implementation
- Architecture registry and auto-detection

**Phase 5 - Architecture-Specific (5 unified tools)**
1. read_fault_registers (CFSR/mcause)
2. read_exception_frame (ARM frame/RISC-V trap frame)
3. check_interrupt_priorities (NVIC/PLIC)
4. show_interrupt_controller (NVIC/PLIC)
5. show_memory_protection (MPU/PMP)

**Phase 6 - Analysis (7 tools)**
1. build_causal_chain
2. validate_fix_hypothesis
3. find_corruption_iteration
4. track_register_changes
5. check_barrier_usage
6. add_comparison_target
7. compare_execution

**Total: 14 existing + 21 new = 35 tools**

---

## Appendix: Architecture Support Matrix

| Feature | ARM Cortex-M | RISC-V | Xtensa (future) |
|---------|--------------|--------|-----------------|
| Fault registers | CFSR, HFSR | mcause, mtval | EXCCAUSE |
| Fault address | MMFAR, BFAR | mtval | EXCVADDR |
| Interrupt controller | NVIC | PLIC/CLIC | INTC |
| Memory protection | MPU | PMP | MPU |
| Exception frame | 8 words | Full regset | Custom |
| Barrier instructions | DSB, ISB | FENCE | MEMW |
| QEMU system | qemu-system-arm | qemu-system-riscv{32,64} | qemu-system-xtensa |

---

*Plan Version 2.0 - January 2026 (Multi-Architecture)*
