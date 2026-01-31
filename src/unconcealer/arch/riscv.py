"""RISC-V architecture support.

Provides trap analysis, interrupt controller (PLIC/CLIC) configuration
checking, and PMP decoding for RISC-V processors.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from unconcealer.arch.base import (
    TargetArchitecture,
    FaultState,
    ExceptionFrame,
    InterruptAnalysis,
    InterruptInfo,
    MemoryProtectionConfig,
    MemoryRegion,
)

if TYPE_CHECKING:
    from unconcealer.core.session import DebugSession


class RiscVTarget(TargetArchitecture):
    """RISC-V architecture support.

    Supports RV32 and RV64 processors with Machine mode.
    Provides trap cause decoding, PLIC analysis, and PMP configuration.

    Example:
        target = RiscVTarget()
        fault = await target.read_fault_state(session)
        print(f"Trap: {fault.fault_type}")
    """

    name = "riscv"
    register_names = [
        "zero", "ra", "sp", "gp", "tp",
        "t0", "t1", "t2",
        "s0", "s1",
        "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
        "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11",
        "t3", "t4", "t5", "t6",
        "pc",
    ]
    pointer_size = 4  # RV32; override for RV64

    # CSR names (accessed via GDB)
    # Machine-mode CSRs
    CSR_MSTATUS = "mstatus"
    CSR_MISA = "misa"
    CSR_MIE = "mie"
    CSR_MTVEC = "mtvec"
    CSR_MSCRATCH = "mscratch"
    CSR_MEPC = "mepc"
    CSR_MCAUSE = "mcause"
    CSR_MTVAL = "mtval"
    CSR_MIP = "mip"

    # PLIC base address (platform-dependent, common for QEMU virt)
    PLIC_BASE = 0x0C000000
    PLIC_PRIORITY_BASE = 0x0C000000
    PLIC_PENDING_BASE = 0x0C001000
    PLIC_ENABLE_BASE = 0x0C002000
    PLIC_THRESHOLD = 0x0C200000
    PLIC_CLAIM = 0x0C200004

    # Exception codes
    EXCEPTION_CODES = {
        0: "Instruction address misaligned",
        1: "Instruction access fault",
        2: "Illegal instruction",
        3: "Breakpoint",
        4: "Load address misaligned",
        5: "Load access fault",
        6: "Store/AMO address misaligned",
        7: "Store/AMO access fault",
        8: "Environment call from U-mode",
        9: "Environment call from S-mode",
        11: "Environment call from M-mode",
        12: "Instruction page fault",
        13: "Load page fault",
        15: "Store/AMO page fault",
    }

    INTERRUPT_CODES = {
        1: "Supervisor software interrupt",
        3: "Machine software interrupt",
        5: "Supervisor timer interrupt",
        7: "Machine timer interrupt",
        9: "Supervisor external interrupt",
        11: "Machine external interrupt",
    }

    async def _read_csr(self, session: "DebugSession", csr_name: str) -> int:
        """Read a CSR via GDB.

        Args:
            session: Active debug session
            csr_name: CSR name (e.g., "mcause")

        Returns:
            CSR value
        """
        result = await session.evaluate(f"${csr_name}")
        # Parse result like "0x00000002"
        try:
            return int(result.split("=")[-1].strip(), 0)
        except (ValueError, IndexError):
            return int(result.strip(), 0)

    def _decode_mcause(self, value: int) -> Dict[str, Any]:
        """Decode mcause into trap type and name."""
        # Bit 31 (RV32) or 63 (RV64) indicates interrupt vs exception
        is_interrupt = bool(value & (1 << (self.pointer_size * 8 - 1)))
        code = value & 0x7FFFFFFF

        if is_interrupt:
            name = self.INTERRUPT_CODES.get(code, f"Unknown interrupt ({code})")
            return {"type": "interrupt", "code": code, "name": name}
        else:
            name = self.EXCEPTION_CODES.get(code, f"Unknown exception ({code})")
            return {"type": "exception", "code": code, "name": name}

    def _determine_fault_type(self, mcause_info: Dict[str, Any]) -> str:
        """Determine high-level fault type from mcause."""
        code = mcause_info["code"]

        if mcause_info["type"] == "interrupt":
            return "interrupt"

        fault_map = {
            0: "instruction_misaligned",
            1: "instruction_access_fault",
            2: "illegal_instruction",
            3: "breakpoint",
            4: "load_misaligned",
            5: "load_access_fault",
            6: "store_misaligned",
            7: "store_access_fault",
            8: "ecall_user",
            9: "ecall_supervisor",
            11: "ecall_machine",
            12: "instruction_page_fault",
            13: "load_page_fault",
            15: "store_page_fault",
        }
        return fault_map.get(code, "unknown_trap")

    async def read_fault_state(self, session: "DebugSession") -> FaultState:
        """Read and decode RISC-V trap state.

        Reads mcause, mtval, and mepc to determine the cause
        of a trap/exception.

        Args:
            session: Active debug session

        Returns:
            FaultState with decoded trap information
        """
        mcause = await self._read_csr(session, self.CSR_MCAUSE)
        mtval = await self._read_csr(session, self.CSR_MTVAL)
        mepc = await self._read_csr(session, self.CSR_MEPC)

        mcause_info = self._decode_mcause(mcause)

        decoded = {
            "trap_type": mcause_info["type"],
            "trap_name": mcause_info["name"],
        }

        # mtval contains fault address for access faults
        fault_address = None
        is_valid = False

        if mcause_info["code"] in (1, 5, 7, 12, 13, 15):
            # Access faults and page faults have valid mtval
            fault_address = mtval
            is_valid = True
        elif mcause_info["code"] == 2:
            # Illegal instruction - mtval may contain the instruction
            decoded["illegal_instruction"] = f"0x{mtval:08x}"

        return FaultState(
            fault_type=self._determine_fault_type(mcause_info),
            fault_address=fault_address,
            is_valid=is_valid,
            raw_registers={
                "mcause": mcause,
                "mtval": mtval,
                "mepc": mepc,
            },
            decoded=decoded,
        )

    async def decode_exception_frame(
        self, session: "DebugSession", stack_pointer: Optional[int] = None
    ) -> ExceptionFrame:
        """Parse RISC-V trap frame.

        RISC-V doesn't automatically push registers on trap entry.
        The trap handler is responsible for saving context. This
        reads the current register state which should reflect
        the saved context if in a trap handler.

        Args:
            session: Active debug session
            stack_pointer: Not used (RISC-V doesn't auto-stack)

        Returns:
            ExceptionFrame with register values
        """
        # Read all general-purpose registers
        regs = await session.read_registers()

        # Get mepc for return address
        mepc = await self._read_csr(session, self.CSR_MEPC)

        return ExceptionFrame(
            registers=regs,
            return_address=mepc,
            stack_pointer=regs.get("sp", 0),
            frame_type="riscv_trap",
        )

    async def check_interrupt_config(
        self, session: "DebugSession"
    ) -> InterruptAnalysis:
        """Analyze interrupt configuration.

        Checks machine-level interrupt enable/pending bits and
        reads PLIC configuration if available.

        Args:
            session: Active debug session

        Returns:
            InterruptAnalysis with configuration and warnings
        """
        # Read machine interrupt enable/pending
        mie = await self._read_csr(session, self.CSR_MIE)
        mip = await self._read_csr(session, self.CSR_MIP)
        mstatus = await self._read_csr(session, self.CSR_MSTATUS)

        enabled = []
        pending = []
        warnings = []

        # Decode MIE bits
        interrupt_bits = {
            3: ("MSI", "Machine Software Interrupt"),
            7: ("MTI", "Machine Timer Interrupt"),
            11: ("MEI", "Machine External Interrupt"),
        }

        for bit, (name, desc) in interrupt_bits.items():
            if mie & (1 << bit):
                enabled.append(InterruptInfo(number=bit, name=name, enabled=True))
            if mip & (1 << bit):
                pending.append(InterruptInfo(number=bit, name=name, pending=True))

        # Check global interrupt enable
        mie_global = bool(mstatus & 0x08)  # MIE bit in mstatus
        if not mie_global:
            warnings.append("Global machine interrupts disabled (mstatus.MIE=0)")

        # Try to read PLIC configuration
        try:
            threshold_data = await session.read_memory(self.PLIC_THRESHOLD, 4)
            threshold = int.from_bytes(threshold_data, "little")

            if threshold > 0:
                warnings.append(
                    f"PLIC threshold is {threshold}. Interrupts with "
                    f"priority <= {threshold} are masked."
                )
        except Exception:
            pass  # PLIC may not be present

        priorities = {
            "MSI": (mie >> 3) & 1,
            "MTI": (mie >> 7) & 1,
            "MEI": (mie >> 11) & 1,
            "global_enable": int(mie_global),
        }

        return InterruptAnalysis(
            enabled=enabled,
            pending=pending,
            priorities=priorities,
            warnings=warnings,
        )

    async def get_memory_protection(
        self, session: "DebugSession"
    ) -> MemoryProtectionConfig:
        """Read PMP (Physical Memory Protection) configuration.

        Reads PMP entries to show protected regions and their
        permissions.

        Args:
            session: Active debug session

        Returns:
            MemoryProtectionConfig with PMP entries
        """
        regions = []

        # Read pmpcfg registers (8 entries per 32-bit register for RV32)
        # PMP entries are configured via pmpcfg0-3 and pmpaddr0-15
        try:
            for i in range(8):  # First 8 PMP entries
                # Read pmpaddr
                pmpaddr = await self._read_csr(session, f"pmpaddr{i}")

                # Read corresponding pmpcfg byte
                cfg_reg = i // 4  # Which pmpcfg register
                cfg_byte = i % 4  # Which byte within register
                pmpcfg = await self._read_csr(session, f"pmpcfg{cfg_reg}")
                cfg = (pmpcfg >> (cfg_byte * 8)) & 0xFF

                if cfg == 0:
                    continue  # Entry not configured

                # Decode PMP config
                r = bool(cfg & 0x01)
                w = bool(cfg & 0x02)
                x = bool(cfg & 0x04)
                a = (cfg >> 3) & 0x03  # Address matching mode
                l = bool(cfg & 0x80)  # Lock bit

                if a == 0:
                    continue  # OFF - entry disabled

                permissions = ""
                permissions += "R" if r else "-"
                permissions += "W" if w else "-"
                permissions += "X" if x else "-"

                # Calculate address range based on mode
                addr_mode = {0: "OFF", 1: "TOR", 2: "NA4", 3: "NAPOT"}

                # pmpaddr is shifted left 2 bits for actual address
                base_addr = pmpaddr << 2

                # Size depends on matching mode
                if a == 2:  # NA4 - naturally aligned 4 bytes
                    size = 4
                elif a == 3:  # NAPOT - naturally aligned power-of-two
                    # Find lowest set bit to determine size
                    if pmpaddr == 0:
                        size = 1 << (self.pointer_size * 8)
                    else:
                        trailing_ones = 0
                        temp = pmpaddr
                        while temp & 1:
                            trailing_ones += 1
                            temp >>= 1
                        size = 1 << (trailing_ones + 3)
                        base_addr = (pmpaddr & ~((1 << trailing_ones) - 1)) << 2
                else:  # TOR - top of range
                    size = 0  # Would need previous entry

                regions.append(
                    MemoryRegion(
                        number=i,
                        base_address=base_addr,
                        size=size,
                        permissions=permissions,
                        enabled=True,
                        attributes={
                            "mode": addr_mode[a],
                            "locked": l,
                        },
                    )
                )

        except Exception:
            pass  # PMP may not be fully accessible

        return MemoryProtectionConfig(
            enabled=len(regions) > 0,
            regions=regions,
            default_permissions="RWX",  # Default if no PMP match
        )


class RiscV32Target(RiscVTarget):
    """RISC-V 32-bit specific target."""

    name = "riscv32"
    pointer_size = 4


class RiscV64Target(RiscVTarget):
    """RISC-V 64-bit specific target."""

    name = "riscv64"
    pointer_size = 8
    register_names = RiscVTarget.register_names  # Same ABI names
